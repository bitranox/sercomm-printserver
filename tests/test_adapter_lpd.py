"""LpdClient against a loopback LPD server: the exact bytes on the wire and every error branch."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fake_lpd_server import FakeLpdServer, closed_port

from sercomm_printserver.adapters.lpd import LpdClient
from sercomm_printserver.domain.endpoint import DeviceEndpoint, PrintJob
from sercomm_printserver.domain.errors import DeviceResponseError, DeviceUnavailableError

if TYPE_CHECKING:
    from sercomm_printserver.application.ports import LpdPort

#: Protocol timing for the silent-server cases, not a test sleep.
_SHORT_TIMEOUT = 0.2
_WAIT = 10.0

_JOB = PrintJob(data=b"%!PS\nshowpage\n", name="report", user="alice", client_host="ws1")

#: The control file this client sends for ``_JOB`` with job number 42.
_CONTROL = b"Hws1\nPalice\nJreport\nldfA042ws1\nUdfA042ws1\nNreport\n"


def _endpoint(port: int, *, timeout: float = 5.0) -> DeviceEndpoint:
    return DeviceEndpoint(host="127.0.0.1", lpd_port=port, timeout=timeout)


def _client() -> LpdClient:
    return LpdClient(job_number=lambda: 42)


def _submit_bytes(queue: bytes, job: PrintJob, control: bytes) -> bytes:
    """Every byte a data-first submission of ``job`` puts on the wire."""
    return (
        b"\x02" + queue + b"\n"
        + b"\x03" + str(len(job.data)).encode() + b" dfA042ws1\n" + job.data + b"\x00"
        + b"\x02" + str(len(control)).encode() + b" cfA042ws1\n" + control + b"\x00"
    )  # fmt: skip


def test_the_client_satisfies_the_port() -> None:
    port: LpdPort = LpdClient()

    assert isinstance(port, LpdClient)


@pytest.mark.parametrize(("long_format", "command"), [(False, b"\x03L1\n"), (True, b"\x04L1\n")])
def test_queue_state_sends_the_command_and_returns_the_reply(long_format: bool, command: bytes) -> None:
    with FakeLpdServer(queue_reply=b"L1: no entries\n\xff") as server:
        text = _client().queue_state(_endpoint(server.port), "L1", long_format=long_format)
        assert server.finished.wait(_WAIT)

    assert bytes(server.received) == command
    assert text == "L1: no entries\n" + chr(0xFFFD)


def test_queue_state_returns_empty_text_when_the_device_closes_without_a_word() -> None:
    with FakeLpdServer() as server:
        text = _client().queue_state(_endpoint(server.port), "lp", long_format=False)
        assert server.finished.wait(_WAIT)

    assert text == ""
    assert bytes(server.received) == b"\x03lp\n"


def test_queue_state_refuses_a_reply_over_64_kib() -> None:
    with (
        FakeLpdServer(queue_reply=b"x" * (64 * 1024 + 1)) as server,
        pytest.raises(DeviceResponseError, match="more than 65536"),
    ):
        _client().queue_state(_endpoint(server.port), "L1", long_format=True)


def test_queue_state_on_a_silent_device_is_unavailable() -> None:
    with FakeLpdServer(silent=True) as server:
        with pytest.raises(DeviceUnavailableError, match=f"127.0.0.1:{server.port}"):
            _client().queue_state(_endpoint(server.port, timeout=_SHORT_TIMEOUT), "L1", long_format=False)
        assert server.finished.wait(_WAIT)

    assert bytes(server.received) == b"\x03L1\n"


def test_a_refused_connection_is_unavailable_and_names_the_address() -> None:
    port = closed_port()

    with pytest.raises(DeviceUnavailableError, match=f"127.0.0.1:{port}"):
        _client().queue_state(_endpoint(port), "L1", long_format=False)


@pytest.mark.parametrize("queue", ["", "L 1", "L1\n", "x" * 32, "L" + chr(0xE4) + "1"])
def test_an_invalid_queue_name_is_refused_before_connecting(queue: str) -> None:
    # A closed port: had the client connected, it would raise DeviceUnavailableError instead.
    endpoint = _endpoint(closed_port())

    with pytest.raises(ValueError, match="queue name") as state_error:
        _client().queue_state(endpoint, queue, long_format=False)
    with pytest.raises(ValueError, match="queue name") as submit_error:
        _client().submit(endpoint, queue, _JOB)

    assert type(state_error.value) is ValueError
    assert type(submit_error.value) is ValueError


def test_submit_sends_the_data_file_first_then_the_control_file() -> None:
    with FakeLpdServer() as server:
        _client().submit(_endpoint(server.port), "L2", _JOB)
        assert server.finished.wait(_WAIT)

    assert bytes(server.received) == _submit_bytes(b"L2", _JOB, _CONTROL)


def test_submit_streams_a_job_larger_than_one_chunk_unchanged() -> None:
    job = PrintJob(data=bytes(range(256)) * 1000, name="report", user="alice", client_host="ws1")

    with FakeLpdServer() as server:
        _client().submit(_endpoint(server.port), "L1", job)
        assert server.finished.wait(_WAIT)

    assert bytes(server.received) == _submit_bytes(b"L1", job, _CONTROL)


def test_the_default_job_number_is_three_digits_in_both_file_names() -> None:
    with FakeLpdServer() as server:
        LpdClient().submit(_endpoint(server.port), "L1", _JOB)
        assert server.finished.wait(_WAIT)

    received = bytes(server.received)
    data_header = received.split(b"\n")[1]
    tag = data_header[-6:-3]
    assert data_header.startswith(b"\x03") and data_header.endswith(b"ws1")
    assert tag.isdigit() and len(tag) == 3
    assert b" cfA" + tag + b"ws1\n" in received


@pytest.mark.parametrize(
    ("step", "name"),
    [
        (0, "receive-job command"),
        (1, "data file header"),
        (2, "data file"),
        (3, "control file header"),
        (4, "control file"),
    ],
)
def test_a_non_zero_acknowledgement_names_the_refused_step(step: int, name: str) -> None:
    with FakeLpdServer(acks={step: b"\x01"}) as server:
        with pytest.raises(DeviceResponseError, match=rf"refused the {name}: acknowledgement b'\\x01'"):
            _client().submit(_endpoint(server.port), "L1", _JOB)
        assert server.finished.wait(_WAIT)


def test_a_device_closing_before_any_answer_is_unavailable() -> None:
    with FakeLpdServer(acks={0: b""}) as server:
        with pytest.raises(DeviceUnavailableError, match="receive-job command"):
            _client().submit(_endpoint(server.port), "L1", _JOB)
        assert server.finished.wait(_WAIT)

    assert bytes(server.received) == b"\x02L1\n"


def test_a_device_closing_after_it_answered_is_a_response_error() -> None:
    with FakeLpdServer(acks={1: b""}) as server:
        with pytest.raises(DeviceResponseError, match="broke off during the data file header"):
            _client().submit(_endpoint(server.port), "L1", _JOB)
        assert server.finished.wait(_WAIT)


def test_a_device_hanging_up_while_the_data_is_sent_is_a_response_error() -> None:
    # Large enough that the client is still writing when the reset arrives; whether sendall or
    # the following acknowledgement read sees it, both belong to the data-file step.
    job = PrintJob(data=b"D" * (4 * 1024 * 1024), client_host="ws1")

    with FakeLpdServer(hang_up_before_data=True) as server:
        with pytest.raises(DeviceResponseError, match="broke off during the data file:"):
            _client().submit(_endpoint(server.port), "L1", job)
        assert server.finished.wait(_WAIT)


def test_submit_on_a_silent_device_is_unavailable() -> None:
    with FakeLpdServer(silent=True) as server:
        with pytest.raises(DeviceUnavailableError, match="did not answer the receive-job command"):
            _client().submit(_endpoint(server.port, timeout=_SHORT_TIMEOUT), "L1", _JOB)
        assert server.finished.wait(_WAIT)

    assert bytes(server.received) == b"\x02L1\n"


def test_an_empty_job_is_refused_before_connecting() -> None:
    with pytest.raises(ValueError, match="at least one byte") as error:
        _client().submit(_endpoint(closed_port()), "L1", PrintJob(data=b""))

    assert type(error.value) is ValueError


@pytest.mark.parametrize("number", [-1, 1000])
def test_a_job_number_outside_0_to_999_is_refused(number: int) -> None:
    with pytest.raises(ValueError, match="outside 0-999"):
        LpdClient(job_number=lambda: number).submit(_endpoint(closed_port()), "L1", _JOB)
