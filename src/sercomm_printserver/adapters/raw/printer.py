"""RAW / direct-socket printing: the bytes go to a TCP port with no protocol around them.

Device behaviour this adapter is shaped by (measured on a PS301, firmware 6022):

* Data sent while no printer takes it stays queued: the port reads ``Printing / Direct
  Socket`` until a restart and blocks every other job. The same state was once seen after a
  port scan; a single connect closed at once left the ports idle, so the cause of that one is
  open. ``send`` therefore refuses empty data before it connects, and never opens a
  connection it does not write to.
* The end of a job is the end of the stream. The adapter half-closes its side
  (``shutdown(SHUT_WR)``) after the last byte, then waits for the device to close, so the
  device sees a clean end of job rather than a dropped connection.
* A RAW port belongs to a logical printer, not to a physical port: 9100-9102 and the vendor's
  DSI sockets 4010/4020/4030 both reach L1..L3, and the data goes wherever that printer is
  routed (``Ln_PROUT``). The caller names the port.
* After a job's connection closes, the port refuses a new connect for about 1-2 s. A refused
  connect is therefore retried for a short window before the device counts as unreachable, so
  two jobs sent back to back both arrive. Other connect errors are not retried.

A device that keeps its side open after the job is not an error: the data was delivered, so a
timeout while waiting for its close returns normally.
"""

from __future__ import annotations

import socket
import time
from typing import TYPE_CHECKING, Final

from ...domain.errors import DeviceUnavailableError

if TYPE_CHECKING:
    from ...domain.endpoint import DeviceEndpoint

_SEND_CHUNK: Final = 64 * 1024
_RECV_SIZE: Final = 4096
#: Bytes the device may send back (status, PJL echo) before the adapter stops waiting for its
#: close; the data is discarded, the cap only bounds a peer that never stops sending.
_DRAIN_LIMIT: Final = 64 * 1024
_MIN_PORT: Final = 1
_MAX_PORT: Final = 65535
#: Longest time a refused connect is retried (never longer than the endpoint's timeout). The
#: PS301 refuses for about 1-2 s after the previous job closed, so 3 s covers it with margin
#: while a port that is really closed still fails quickly.
_REFUSED_RETRY_SECONDS: Final = 3.0
_REFUSED_RETRY_INTERVAL: Final = 0.25


def _check_arguments(port: int, data: bytes) -> None:
    """Refuse what must never reach the device, before any connection is opened."""
    if not data:
        raise ValueError("refusing to send empty data: a bare connect blocks the RAW port for minutes")
    if not _MIN_PORT <= port <= _MAX_PORT:
        raise ValueError(f"port must be {_MIN_PORT}..{_MAX_PORT}, got {port}")


def _connect(host: str, port: int, timeout: float) -> socket.socket:
    """Open the TCP connection, mapping every failure to ``DeviceUnavailableError``."""
    try:
        return _connect_retrying_refusals(host, port, timeout)
    except (OSError, UnicodeError) as exc:
        # UnicodeError: the IDNA codec refuses a malformed host name before any socket exists.
        raise DeviceUnavailableError(f"{host}:{port} could not be reached: {exc}") from exc


def _connect_retrying_refusals(host: str, port: int, timeout: float) -> socket.socket:
    """Connect, retrying a refused connect until the retry window closes.

    The last attempt catches nothing, so a port that keeps refusing raises its own
    ``ConnectionRefusedError`` and the caller's message names the real cause.
    """
    deadline = time.monotonic() + min(timeout, _REFUSED_RETRY_SECONDS)
    while time.monotonic() + _REFUSED_RETRY_INTERVAL < deadline:
        sock = _connect_unless_refused(host, port, timeout)
        if sock is not None:
            return sock
        time.sleep(_REFUSED_RETRY_INTERVAL)
    return socket.create_connection((host, port), timeout=timeout)


def _connect_unless_refused(host: str, port: int, timeout: float) -> socket.socket | None:
    """Connect once; ``None`` when the port refused, every other error propagates."""
    try:
        return socket.create_connection((host, port), timeout=timeout)
    except ConnectionRefusedError:
        return None


def _transmit(sock: socket.socket, data: bytes, *, address: str) -> None:
    """Send every byte, counting them so a broken connection says how far the job got.

    ``sendall`` would hide that count, which is what tells the caller whether a partial job
    may already be on paper.
    """
    view = memoryview(data)
    sent = 0
    try:
        while sent < len(view):
            sent += sock.send(view[sent : sent + _SEND_CHUNK])
    except OSError as exc:
        raise DeviceUnavailableError(
            f"{address} broke the connection after {sent} of {len(view)} bytes were sent: {exc}"
        ) from exc


def _finish(sock: socket.socket, *, address: str, total: int) -> None:
    """Half-close, then wait for the device's close so the job ends cleanly.

    A reset at this point means the device dropped the connection before it read the whole
    stream, so delivery cannot be confirmed and it is reported.
    """
    received = 0
    try:
        sock.shutdown(socket.SHUT_WR)
        while received < _DRAIN_LIMIT:
            reply = sock.recv(_RECV_SIZE)
            if not reply:
                return
            received += len(reply)
    except TimeoutError:
        return
    except OSError as exc:
        raise DeviceUnavailableError(
            f"{address} broke the connection after all {total} bytes were sent; delivery is unconfirmed: {exc}"
        ) from exc


class RawPrinter:
    """``RawPort`` over a plain TCP socket, one connection per call.

    Example:
        >>> from sercomm_printserver.application.ports import RawPort
        >>> from sercomm_printserver.domain.endpoint import DeviceEndpoint
        >>> port: RawPort = RawPrinter()
        >>> RawPrinter().send(DeviceEndpoint(host="192.0.2.52"), 9100, b"")
        Traceback (most recent call last):
        ...
        ValueError: refusing to send empty data: a bare connect blocks the RAW port for minutes
    """

    def send(self, endpoint: DeviceEndpoint, port: int, data: bytes) -> None:
        """Connect to ``port``, send ``data``, half-close and wait for the device to close.

        Args:
            endpoint: The device; ``host`` and ``timeout`` are used. ``timeout`` bounds each
                connect attempt, each send and the wait for the device's close; a refused
                connect is retried for up to 3 s, never longer than ``timeout``.
            port: The RAW TCP port (9100-9102 or 4010/4020/4030 for L1..L3).
            data: The print data, sent unchanged.

        Raises:
            ValueError: ``data`` is empty or ``port`` is outside 1..65535; nothing is sent.
            DeviceUnavailableError: The device could not be reached (a refusal still stood after
                the retry window), or broke the connection;
                the message says how many bytes were sent.
        """
        _check_arguments(port, data)
        address = f"{endpoint.host}:{port}"
        with _connect(endpoint.host, port, endpoint.timeout) as sock:
            _transmit(sock, data, address=address)
            _finish(sock, address=address, total=len(data))


__all__ = ["RawPrinter"]
