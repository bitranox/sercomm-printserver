"""RawPrinter against a loopback RAW port that records what it received."""

from __future__ import annotations

import errno
import io
import re
import socket
import threading
import time
from typing import TYPE_CHECKING

import pytest
from fake_lpd_server import closed_port
from fake_raw_server import FakeRawServer, RawBehaviour
from print_sources import pipe_with

from sercomm_printserver.adapters.raw import RawPrinter
from sercomm_printserver.domain.endpoint import DeviceEndpoint
from sercomm_printserver.domain.errors import DeviceUnavailableError
from sercomm_printserver.domain.link import DRAIN_MARGIN_SECONDS, LinkDrain
from sercomm_printserver.domain.print_data import PrintData

if TYPE_CHECKING:
    from pathlib import Path

    from sercomm_printserver.application.ports import RawPort

pytestmark = pytest.mark.os_agnostic

#: Long enough that no healthy loopback exchange times out; the hang test uses _SHORT instead.
_PATIENT = 5.0
#: How long the client waits on a peer that deliberately never closes.
_SHORT = 0.3
#: Every byte value, many times over: more than one send chunk and more than one recv buffer.
_JOB = bytes(range(256)) * 1024


def _endpoint(timeout: float = _PATIENT) -> DeviceEndpoint:
    return DeviceEndpoint(host="127.0.0.1", timeout=timeout)


def test_the_printer_satisfies_the_raw_port() -> None:
    port: RawPort = RawPrinter()

    assert callable(port.send)


def test_send_delivers_every_byte_then_half_closes() -> None:
    # The fake closes only after it sees end of stream. With a 30 s timeout, a client that did
    # not half-close would sit in its wait for the close until that timeout; a prompt return
    # proves the half-close is what ended the job.
    with FakeRawServer() as server:
        started = time.monotonic()
        RawPrinter().send(_endpoint(timeout=30.0), server.port, _JOB)
        elapsed = time.monotonic() - started

    assert server.received == _JOB
    assert server.saw_half_close
    assert elapsed < 9.0


def test_a_reply_from_the_device_is_read_and_discarded() -> None:
    with FakeRawServer(reply=b"@PJL USTATUS DEVICE\r\nCODE=10001\r\n\x0c") as server:
        RawPrinter().send(_endpoint(), server.port, b"%!PS\nshowpage\n")

    assert server.received == b"%!PS\nshowpage\n"


def test_empty_data_is_refused_before_any_connection() -> None:
    with FakeRawServer() as server, pytest.raises(ValueError, match="refusing to send empty data"):
        RawPrinter().send(_endpoint(), server.port, b"")

    assert server.connections == 0


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_a_port_outside_the_tcp_range_is_refused(port: int) -> None:
    with pytest.raises(ValueError, match=re.escape("port must be 1..65535")):
        RawPrinter().send(_endpoint(), port, b"x")


def test_a_device_that_keeps_its_side_open_still_counts_as_delivered() -> None:
    with FakeRawServer(behaviour=RawBehaviour.NEVER_CLOSE) as server:
        RawPrinter().send(_endpoint(timeout=_SHORT), server.port, _JOB)

    assert server.received == _JOB
    assert server.saw_half_close


def test_the_wait_for_the_close_stops_at_the_drain_cap() -> None:
    # The fake never closes before the test ends, so only the cap can end the wait early;
    # without it the call would last until the fake's 10 s guard.
    flood = b"S" * (256 * 1024)
    with FakeRawServer(behaviour=RawBehaviour.NEVER_CLOSE, reply=flood) as server:
        started = time.monotonic()
        RawPrinter().send(_endpoint(timeout=30.0), server.port, b"job")
        elapsed = time.monotonic() - started

    assert server.received == b"job"
    assert elapsed < 9.0


def test_a_reset_mid_stream_is_unavailable_and_says_how_far_the_job_got() -> None:
    big_job = _JOB * 32  # 8 MiB: more than the loopback buffers hold, so the reset meets a send
    with (
        FakeRawServer(behaviour=RawBehaviour.RESET_MID_STREAM, reset_after=1024) as server,
        pytest.raises(DeviceUnavailableError, match=r"broke the connection after .*bytes were sent") as caught,
    ):
        RawPrinter().send(_endpoint(), server.port, big_job)

    assert f"127.0.0.1:{server.port}" in str(caught.value)
    assert len(server.received) >= 1024
    assert big_job.startswith(bytes(server.received))


def test_a_refused_connection_is_unavailable_and_names_the_address() -> None:
    port = closed_port()

    started = time.monotonic()
    with pytest.raises(DeviceUnavailableError, match=re.escape(f"127.0.0.1:{port} refused every connection")):
        RawPrinter().send(_endpoint(), port, b"job")
    elapsed = time.monotonic() - started

    # The refusal is retried for a bounded window, then given up. Windows takes about 2 s to
    # report each refused attempt (measured: 2.07 s), so the bound allows for one more attempt
    # after the 3 s window.
    assert elapsed < 9.0


def test_a_port_that_keeps_refusing_points_at_a_restart() -> None:
    # A PS301 RAW port can refuse every connect for minutes while the monitor shows the port
    # idle, so status cannot reveal it; the message is the only place the user learns that a
    # restart clears it. The full patient timeout: on Windows a refused connect takes about 2 s
    # to be reported, and a timeout below that turns the refusal into a plain TimeoutError.
    with pytest.raises(DeviceUnavailableError) as caught:
        RawPrinter().send(_endpoint(), closed_port(), b"job")

    message = str(caught.value)
    assert "refused every connection for 3 s" in message
    assert "status does not show" in message
    assert "reset" in message


def _accept_one_job(listener: socket.socket, received: bytearray) -> None:
    conn, _ = listener.accept()
    with conn:
        while chunk := conn.recv(4096):
            received += chunk


def test_a_port_that_refuses_for_a_moment_after_a_job_still_takes_the_next_one() -> None:
    # A PS301 RAW port refuses a new connect for about 1-2 s after the previous job closed. Here
    # the port refuses (nothing listens) until a listener opens on it 0.8 s later.
    received = bytearray()
    port = closed_port()

    def listen_late() -> None:
        time.sleep(0.8)
        with socket.create_server(("127.0.0.1", port)) as listener:
            _accept_one_job(listener, received)

    worker = threading.Thread(target=listen_late, daemon=True)
    worker.start()
    RawPrinter().send(_endpoint(), port, b"second job")
    worker.join(_PATIENT)

    assert bytes(received) == b"second job"


def test_a_malformed_host_name_is_unavailable_not_a_raw_codec_error() -> None:
    with pytest.raises(DeviceUnavailableError, match=re.escape("bad..host:9100 could not be reached")):
        RawPrinter().send(DeviceEndpoint(host="bad..host", timeout=_PATIENT), 9100, b"job")


# ---------------------------------------------------------------------- the drain wait


class _RecordingSleep:
    """A sleep that records what it was asked for and whether the job had ended by then.

    It really sleeps a little before looking, so a client that half-closed BEFORE its wait has
    given the fake time to see the end of stream, and the test reads ``True``.
    """

    def __init__(self, server: FakeRawServer) -> None:
        self._server = server
        self.waits: list[float] = []
        self.half_closed_during_wait: list[bool] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        time.sleep(0.2)
        self.half_closed_during_wait.append(self._server.saw_half_close)


class _FrozenClock:
    def __call__(self) -> float:
        return 100.0


def test_with_a_link_the_connection_stays_open_for_the_drain_before_the_half_close() -> None:
    job = b"J" * 1920
    with FakeRawServer() as server:
        sleep = _RecordingSleep(server)
        printer = RawPrinter(sleep=sleep, clock=_FrozenClock())
        printer.send(_endpoint(), server.port, job, drain=LinkDrain(bytes_per_second=960.0))

    assert sleep.waits == [pytest.approx(2.0 + DRAIN_MARGIN_SECONDS)]
    assert sleep.half_closed_during_wait == [False]
    assert server.saw_half_close
    assert server.received == job


def test_time_the_send_itself_took_counts_towards_the_drain() -> None:
    # The device passes bytes on while later ones are still being sent, so a send that took
    # time leaves less to wait for once it is done.
    ticks = iter([10.0, 10.5])

    def clock() -> float:
        return next(ticks, 10.5)

    with FakeRawServer() as server:
        sleep = _RecordingSleep(server)
        RawPrinter(sleep=sleep, clock=clock).send(
            _endpoint(), server.port, b"J" * 960, drain=LinkDrain(bytes_per_second=960.0, margin=0.0)
        )

    assert sleep.waits == [pytest.approx(0.5)]


def test_without_a_link_nothing_waits() -> None:
    with FakeRawServer() as server:
        sleep = _RecordingSleep(server)
        RawPrinter(sleep=sleep, clock=_FrozenClock()).send(_endpoint(), server.port, b"job")

    assert sleep.waits == []
    assert server.received == b"job"


def test_a_failed_send_does_not_wait_for_a_drain() -> None:
    big_job = _JOB * 32
    with FakeRawServer(behaviour=RawBehaviour.RESET_MID_STREAM, reset_after=1024) as server:
        sleep = _RecordingSleep(server)
        with pytest.raises(DeviceUnavailableError):
            RawPrinter(sleep=sleep, clock=_FrozenClock()).send(
                _endpoint(), server.port, big_job, drain=LinkDrain(bytes_per_second=960.0)
            )

    assert sleep.waits == []


# ---------------------------------------------------------------------- the connect probe


def test_a_port_that_accepts_is_reported_open_and_gets_no_data() -> None:
    with FakeRawServer() as server:
        assert RawPrinter().accepts_connection(_endpoint(), server.port) is True

    assert server.connections == 1
    assert server.received == b""


def test_a_port_that_keeps_refusing_is_reported_closed() -> None:
    # The full patient timeout: Windows reports a refused connect only after about 2 s.
    assert RawPrinter().accepts_connection(_endpoint(), closed_port()) is False


def test_a_port_that_refuses_for_a_moment_is_reported_open() -> None:
    port = closed_port()
    accepted = threading.Event()

    def listen_late() -> None:
        time.sleep(0.8)
        with socket.create_server(("127.0.0.1", port)) as listener:
            conn, _ = listener.accept()
            conn.close()
            accepted.set()

    worker = threading.Thread(target=listen_late, daemon=True)
    worker.start()
    assert RawPrinter().accepts_connection(_endpoint(), port) is True
    worker.join(_PATIENT)
    assert accepted.is_set()


def test_a_probe_of_an_unreachable_host_is_unavailable() -> None:
    with pytest.raises(DeviceUnavailableError, match=re.escape("bad..host:9100 could not be reached")):
        RawPrinter().accepts_connection(DeviceEndpoint(host="bad..host", timeout=_PATIENT), 9100)


@pytest.mark.parametrize("port", [0, 65536])
def test_a_probe_outside_the_tcp_range_is_refused(port: int) -> None:
    with pytest.raises(ValueError, match=re.escape("port must be 1..65535")):
        RawPrinter().accepts_connection(_endpoint(), port)


# ---------------------------------------------------------------------- streaming sources


def _file(tmp_path: Path, content: bytes) -> Path:
    path = tmp_path / "job.prn"
    path.write_bytes(content)
    return path


class _FailingRead(io.BytesIO):
    """A stream whose second read fails, as a file on a failing disk does."""

    def __init__(self) -> None:
        super().__init__(b"")
        self.reads = 0

    def read(self, size: int | None = -1, /) -> bytes:
        self.reads += 1
        if self.reads > 1:
            raise OSError(errno.EIO, "Input/output error")
        return b"first piece"


def test_send_returns_the_number_of_bytes_sent() -> None:
    with FakeRawServer() as server:
        sent = RawPrinter().send(_endpoint(), server.port, _JOB)

    assert sent == len(_JOB)


def test_a_job_from_a_path_is_sent_as_its_file_holds_it(tmp_path: Path) -> None:
    with FakeRawServer() as server:
        sent = RawPrinter().send(_endpoint(), server.port, PrintData.from_path(_file(tmp_path, _JOB)))

    assert sent == len(_JOB)
    assert server.received == _JOB


def test_a_job_from_an_open_regular_file_is_sent_whole(tmp_path: Path) -> None:
    with FakeRawServer() as server, _file(tmp_path, _JOB).open("rb") as stream:
        sent = RawPrinter().send(_endpoint(), server.port, PrintData.from_stream(stream))

    assert sent == len(_JOB)
    assert server.received == _JOB


def test_a_job_from_a_pipe_is_sent_whole_and_its_size_is_returned() -> None:
    with FakeRawServer() as server, pipe_with(_JOB) as reader:
        sent = RawPrinter().send(_endpoint(), server.port, PrintData.from_stream(reader))

    assert sent == len(_JOB)
    assert server.received == _JOB


def test_an_empty_pipe_is_refused_before_any_connection() -> None:
    with (
        FakeRawServer() as server,
        pipe_with(b"") as reader,
        pytest.raises(ValueError, match="refusing to send empty data"),
    ):
        RawPrinter().send(_endpoint(), server.port, PrintData.from_stream(reader))

    assert server.connections == 0


def test_an_empty_file_is_refused_before_any_connection(tmp_path: Path) -> None:
    with FakeRawServer() as server, pytest.raises(ValueError, match="refusing to send empty data"):
        RawPrinter().send(_endpoint(), server.port, PrintData.from_path(_file(tmp_path, b"")))

    assert server.connections == 0


def test_a_reset_mid_stream_of_a_pipe_says_the_total_is_unknown() -> None:
    with (
        FakeRawServer(behaviour=RawBehaviour.RESET_MID_STREAM, reset_after=1024) as server,
        pipe_with(_JOB * 32) as reader,
        pytest.raises(DeviceUnavailableError, match=r"after \d+ bytes of a job of unknown size were sent"),
    ):
        RawPrinter().send(_endpoint(), server.port, PrintData.from_stream(reader))


def test_a_source_that_fails_to_read_is_not_reported_as_the_device_breaking_off() -> None:
    with FakeRawServer() as server, pytest.raises(OSError, match="Input/output error") as caught:
        RawPrinter().send(_endpoint(), server.port, PrintData.from_stream(_FailingRead()))

    assert not isinstance(caught.value, DeviceUnavailableError)
