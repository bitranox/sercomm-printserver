"""The wedge probe's trial logic against the in-memory device, and its query over loopback."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest
from ps301_wedge_probe import (
    Arm,
    Options,
    ProbeAbortedError,
    Target,
    Tools,
    Trial,
    main,
    query_answer,
    run,
    run_trial,
    schedule,
    summarise,
)

from sercomm_printserver.adapters.memory.device import FakeDevice, FakeTftp
from sercomm_printserver.application.print_server import DevicePorts, PrintServer
from sercomm_printserver.domain.config_types import PortId
from sercomm_printserver.domain.device_files import DeviceAction
from sercomm_printserver.domain.endpoint import DeviceEndpoint
from sercomm_printserver.domain.link import LinkDrain
from sercomm_printserver.domain.port_health import PortVerdict

pytestmark = pytest.mark.os_agnostic

_DUMPS = Path(__file__).resolve().parents[1] / "docs" / "device-dump"
_ENDPOINT = DeviceEndpoint(host="192.0.2.52")
_IDLE = (
    "(P1)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: On-Line\r\n\r\n"
    "(P2)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: On-Line\r\n\r\n"
    "(SP)STATE: Idle\r\nTYPE: Serial\r\nPRINTER STATUS: On-Line\r\n"
)
_WEDGED = _IDLE.replace(
    "(SP)STATE: Idle\r\nTYPE: Serial\r\nPRINTER STATUS: On-Line\r\n",
    "(SP)STATE: Printing\r\nTYPE: Serial\r\nPRINTER STATUS: On-Line\r\n"
    "BYTES SERVICED:          0\r\nOCCUPIED BY: Direct Socket\r\n",
)
_DRAIN = LinkDrain(bytes_per_second=960.0)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _Query:
    """Answers the probe's query from a script, oldest first."""

    def __init__(self, *answers: bytes) -> None:
        self._answers = list(answers)
        self.asked: list[tuple[int, bytes]] = []

    def __call__(self, endpoint: DeviceEndpoint, port: int, query: bytes, wait: float) -> bytes:
        self.asked.append((port, query))
        return self._answers.pop(0) if self._answers else b"OK"


def _device() -> FakeDevice:
    device = FakeDevice(
        config=(_DUMPS / "CONFIG.txt").read_text(encoding="ascii"),
        psinf=(_DUMPS / "PSINF.txt").read_text(encoding="ascii"),
        monitor=_IDLE,
    )
    device.restart_after_reads = 1
    return device


def _tools(device: FakeDevice, query: _Query, clock: _Clock) -> Tools:
    ports = DevicePorts(ftp=device, telnet=device, tftp=FakeTftp(device), lpd=device, raw=device, uptime=device)
    server = PrintServer(_ENDPOINT, ports)
    return Tools(server=server, raw=device, query=query, sleep=clock.sleep, clock=clock)


def _target() -> Target:
    return Target(
        endpoint=_ENDPOINT,
        printer=3,
        raw_port=9102,
        routed=PortId.SP,
        drain=_DRAIN,
        job=b"J" * 1920,
        query=b"\x01A",
        answer_wait=5.0,
    )


def test_arms_alternate_within_each_round() -> None:
    assert [(number, arm.value) for number, arm in schedule(3)] == [
        (1, "wait"),
        (1, "close"),
        (2, "wait"),
        (2, "close"),
        (3, "wait"),
        (3, "close"),
    ]


def test_the_wait_arm_sends_with_the_drain_and_the_close_arm_without() -> None:
    device, clock = _device(), _Clock()
    tools = _tools(device, _Query(), clock)

    waited = run_trial(_target(), tools, number=1, arm=Arm.WAIT)
    closed = run_trial(_target(), tools, number=1, arm=Arm.CLOSE)

    assert device.raw_drains == [_DRAIN, None]
    assert (waited.drain_seconds, closed.drain_seconds) == (2.25, 0.0)
    assert (waited.wedged, closed.wedged) == (False, False)
    assert device.actions == []


def test_the_query_goes_out_at_once_and_the_checks_follow_at_their_marks() -> None:
    device, clock, query = _device(), _Clock(), _Query()

    trial = run_trial(_target(), _tools(device, query, clock), number=1, arm=Arm.CLOSE)

    assert query.asked == [(9102, b"\x01A")]
    assert clock.sleeps == [1.0, 4.0, 10.0]
    assert trial.verdicts == {"+1s": PortVerdict.IDLE, "+5s": PortVerdict.IDLE, "+15s": PortVerdict.IDLE}
    assert trial.answer == b"OK".hex()


def test_an_unanswered_query_is_a_wedge_and_restarts_the_device() -> None:
    device, clock = _device(), _Clock()

    trial = run_trial(_target(), _tools(device, _Query(b""), clock), number=1, arm=Arm.CLOSE)

    assert (trial.answered, trial.wedged, trial.restarted) == (False, True, True)
    assert device.actions == [DeviceAction.RESET]


def test_a_port_reading_wedged_at_the_last_mark_is_a_wedge() -> None:
    device, clock = _device(), _Clock()
    # Before the trial, then +1 s and +5 s idle, then wedged at +15 s.
    device.monitor_replies = [_IDLE, _IDLE, _IDLE, _WEDGED]

    trial = run_trial(_target(), _tools(device, _Query(), clock), number=1, arm=Arm.CLOSE)

    assert trial.verdicts["+15s"] is PortVerdict.WEDGED
    assert trial.wedged is True
    assert device.actions == [DeviceAction.RESET]


def test_a_port_that_is_not_idle_before_the_trial_stops_the_run_with_nothing_sent() -> None:
    device, clock = _device(), _Clock()
    device.monitor_text = _WEDGED

    with pytest.raises(ProbeAbortedError, match="SP reads wedged before the trial; nothing was sent"):
        run_trial(_target(), _tools(device, _Query(), clock), number=1, arm=Arm.WAIT)
    assert device.raw_sends == []


def _trial(arm: Arm, *, wedged: bool) -> Trial:
    return Trial(
        round=1,
        arm=arm,
        job_bytes=1,
        drain_seconds=0.0,
        answer="",
        answered=not wedged,
        verdicts={},
        wedged=wedged,
        restarted=wedged,
    )


@pytest.mark.parametrize(
    ("close_wedged", "wait_wedged", "reading"),
    [
        ((True, True, False), (False, False, False), "the drain wait held"),
        ((True, False, False), (False, False, False), "the liveness control failed"),
        ((True, True, True), (False, True, False), "the drain wait is too short"),
    ],
)
def test_the_summary_applies_the_pre_registered_reading(
    close_wedged: tuple[bool, ...], wait_wedged: tuple[bool, ...], reading: str
) -> None:
    trials = [_trial(Arm.CLOSE, wedged=w) for w in close_wedged] + [_trial(Arm.WAIT, wedged=w) for w in wait_wedged]

    summary = summarise(trials)

    assert summary.reading.startswith(reading)
    assert summary.trials == {Arm.WAIT: 3, Arm.CLOSE: 3}
    assert summary.wedged[Arm.CLOSE] == sum(close_wedged)


def test_a_run_logs_every_trial_and_the_summary(tmp_path: Path) -> None:
    device, clock = _device(), _Clock()
    log = tmp_path / "wedge.jsonl"

    options = Options(
        host="192.0.2.52",
        printer=3,
        job=tmp_path / "job",
        query=tmp_path / "query",
        log=log,
        rounds=2,
        answer_wait=5.0,
        timeout=10.0,
        raw_port_base=9100,
    )

    run(options, _tools(device, _Query(), clock), _target())

    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [line["kind"] for line in lines] == ["Trial", "Trial", "Trial", "Trial", "Summary"]
    assert [line["arm"] for line in lines[:4]] == ["wait", "close", "wait", "close"]


def test_the_probe_refuses_to_run_without_confirming_that_it_prints(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["--host", "192.0.2.52", "--printer", "3", "--job", "j", "--query", "q", "--log", "l"]

    with pytest.raises(SystemExit) as caught:
        main(argv)

    assert caught.value.code == 2
    assert "--confirm-print" in capsys.readouterr().err


def _answering_server(reply: bytes) -> tuple[socket.socket, threading.Thread, list[bytes]]:
    listener = socket.create_server(("127.0.0.1", 0))
    received: list[bytes] = []

    def serve() -> None:
        conn, _ = listener.accept()
        with conn:
            received.append(conn.recv(4096))
            if reply:
                conn.sendall(reply)
                conn.recv(4096)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    return listener, worker, received


def test_the_query_returns_what_the_printer_answered() -> None:
    listener, worker, received = _answering_server(b"MODULE: A\r")
    with listener:
        port = listener.getsockname()[1]
        answer = query_answer(DeviceEndpoint(host="127.0.0.1", timeout=5.0), port, b"\x01A", 5.0)
        worker.join(5.0)

    assert answer == b"MODULE: A\r"
    assert received == [b"\x01A"]


def test_a_query_nobody_answers_returns_nothing() -> None:
    listener, worker, _ = _answering_server(b"")
    with listener:
        port = listener.getsockname()[1]
        answer = query_answer(DeviceEndpoint(host="127.0.0.1", timeout=5.0), port, b"\x01A", 0.3)
        worker.join(5.0)

    assert answer == b""
