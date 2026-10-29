"""RawPrinter against a loopback RAW port that records what it received."""

from __future__ import annotations

import re
import socket
import threading
import time
from typing import TYPE_CHECKING

import pytest
from fake_raw_server import FakeRawServer, RawBehaviour

from sercomm_printserver.adapters.raw import RawPrinter
from sercomm_printserver.domain.endpoint import DeviceEndpoint
from sercomm_printserver.domain.errors import DeviceUnavailableError

if TYPE_CHECKING:
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


def _released_port() -> int:
    """A loopback port nothing listens on, so every connect to it is refused.

    The port is bound and released at once. A port that stays bound without listening is not
    portable: macOS answers it with no reset at all, so the connect hangs until its timeout
    (CI, macos-latest). Another process could take the released port before the test connects,
    but with a random ephemeral port that is not worth a fixture.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_a_refused_connection_is_unavailable_and_names_the_address() -> None:
    port = _released_port()

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
        RawPrinter().send(_endpoint(), _released_port(), b"job")

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
    port = _released_port()

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
