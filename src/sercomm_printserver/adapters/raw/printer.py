"""RAW / direct-socket printing: the bytes go to a TCP port with no protocol around them.

Device behaviour this adapter is shaped by (measured on a PS301, firmware 6022):

* Data sent while no printer takes it stays queued: the port reads ``Printing / Direct
  Socket`` until a restart and blocks every other job. ``send`` therefore refuses empty data
  before it connects; for a stream of unknown size (a pipe) it reads the first piece to know,
  and sends that piece first. A bare connect closed at once leaves the port idle (measured 2026-11-10:
  clean closes, 20-connect bursts and resets all left it idle), which ``accepts_connection``
  relies on.
* The device takes a whole job at once and passes it on at the speed of the printer's link. A
  NEW connection opened before that is finished loses its data and leaves the port reading
  ``Printing / Direct Socket`` with 0 bytes serviced until a restart. Given the link, ``send``
  keeps the connection fully open until every byte has had time to cross it, plus a margin,
  and only then half-closes. A half-close protects nothing: the device closes about 0.07 s
  after the end of stream, long before the printer has the data.
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

import itertools
import socket
import time
from typing import TYPE_CHECKING, Final

from ...domain.errors import DeviceUnavailableError
from ...domain.print_data import PrintData

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from ...domain.endpoint import DeviceEndpoint
    from ...domain.link import LinkDrain
    from ...domain.print_data import Piece

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


_EMPTY_DATA: Final = "refusing to send empty data: an empty job can leave the RAW port blocked for minutes"


def _check_port(port: int) -> None:
    if not _MIN_PORT <= port <= _MAX_PORT:
        raise ValueError(f"port must be {_MIN_PORT}..{_MAX_PORT}, got {port}")


def _connect(host: str, port: int, timeout: float) -> socket.socket:
    """Open the TCP connection, mapping every failure to ``DeviceUnavailableError``.

    A refusal that outlasts the retry window gets its own message: a PS301 RAW port has been
    measured refusing every connect for minutes while the Telnet monitor showed the port idle,
    so ``status`` cannot reveal that state and the message is the one place that says a restart
    clears it. A port that is simply closed refuses the same way, hence "may".
    """
    try:
        return connect_retrying_refusals(host, port, timeout)
    except ConnectionRefusedError as exc:
        window = min(timeout, _REFUSED_RETRY_SECONDS)
        raise DeviceUnavailableError(
            f"{host}:{port} refused every connection for {window:g} s ({exc}). If this is the RAW "
            "port of a print server that otherwise answers, the port may be stuck refusing; "
            "status does not show that state, and a restart (reset) clears it"
        ) from exc
    except (OSError, UnicodeError) as exc:
        # UnicodeError: the IDNA codec refuses a malformed host name before any socket exists.
        raise DeviceUnavailableError(f"{host}:{port} could not be reached: {exc}") from exc


def connect_retrying_refusals(host: str, port: int, timeout: float) -> socket.socket:
    """Connect, retrying a refused connect until the retry window closes.

    The last attempt catches nothing, so a port that keeps refusing raises its own
    ``ConnectionRefusedError`` and the caller's message names the real cause. Windows retries a
    refused SYN itself and reports the refusal only after about 2 s (measured 2.07 s), so there a
    ``timeout`` below that ends each attempt as a plain timeout, which is not retried.

    Args:
        host: Address of the print server.
        port: TCP port to connect to.
        timeout: Seconds per connect attempt; the retry window is the shorter of this and
            the module's refusal window.

    Returns:
        The connected socket, with ``timeout`` set.

    Raises:
        ConnectionRefusedError: The port refused every attempt in the window.
        OSError: Any other connect failure, at once.
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


class _DrainClock:
    """When the device has passed on every byte the socket took so far, at the link's rate.

    Counted per send from the bytes the socket accepted, so the wait never covers bytes that did
    not leave this host. Bytes cross the link while later ones are still being sent, so each
    send's share starts when it was sent or when the previous share ends, whichever is later.
    """

    def __init__(self, drain: LinkDrain | None, clock: Callable[[], float]) -> None:
        self._drain = drain
        self._clock = clock
        self._carried_at: float | None = None

    def note(self, size: int) -> None:
        if self._drain is None:
            return
        now = self._clock()
        start = now if self._carried_at is None else max(now, self._carried_at)
        self._carried_at = start + size / self._drain.bytes_per_second

    def remaining(self) -> float:
        """Seconds still to wait, margin included; 0 without a link."""
        if self._drain is None or self._carried_at is None:
            return 0.0
        return max(0.0, self._carried_at + self._drain.margin - self._clock())


def _transmit(
    sock: socket.socket, pieces: Iterable[Piece], *, address: str, total: int | None, carried: _DrainClock
) -> int:
    """Send every piece, counting the bytes so a broken connection says how far the job got.

    ``sendall`` would hide that count, which is what tells the caller whether a partial job
    may already be on paper. Only the socket's errors are the device's: a piece that fails to
    be READ (a failing disk) propagates as the error it is.
    """
    sent = 0
    for piece in pieces:
        view = memoryview(piece)
        offset = 0
        while offset < len(view):
            try:
                taken = sock.send(view[offset:])
            except OSError as exc:
                progress = f"{sent} of {total} bytes" if total is not None else f"{sent} bytes of a job of unknown size"
                raise DeviceUnavailableError(
                    f"{address} broke the connection after {progress} were sent: {exc}"
                ) from exc
            offset += taken
            sent += taken
            carried.note(taken)
    return sent


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

    Args:
        sleep: The pause the drain wait sleeps with (injected so tests do not wait).
        clock: The monotonic clock the drain wait is timed with.

    Example:
        >>> from sercomm_printserver.application.ports import RawPort
        >>> from sercomm_printserver.domain.endpoint import DeviceEndpoint
        >>> port: RawPort = RawPrinter()
        >>> RawPrinter().send(DeviceEndpoint(host="192.0.2.52"), 9100, PrintData.of(b""))
        Traceback (most recent call last):
        ...
        ValueError: refusing to send empty data: an empty job can leave the RAW port blocked for minutes
    """

    def __init__(
        self, *, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._sleep = sleep
        self._clock = clock

    def send(
        self, endpoint: DeviceEndpoint, port: int, data: PrintData | bytes, *, drain: LinkDrain | None = None
    ) -> int:
        """Connect to ``port``, send ``data``, wait for the link, half-close, wait for the device to close.

        Args:
            endpoint: The device; ``host`` and ``timeout`` are used. ``timeout`` bounds each
                connect attempt, each send and the wait for the device's close; a refused
                connect is retried for up to 3 s, never longer than ``timeout``.
            port: The RAW TCP port (9100-9102 or 4010/4020/4030 for L1..L3).
            data: The print data, sent unchanged piece by piece; plain bytes are wrapped.
            drain: The link the device passes the job on over. With it the connection stays
                open until the bytes the socket took have had time to cross it, plus its
                margin; without it the job ends as soon as the last byte is sent. A send that
                fails raises at once and does not wait.

        Returns:
            The number of bytes sent: the job's size, also for a stream that could not tell it.

        Raises:
            ValueError: ``data`` is empty or ``port`` is outside 1..65535; nothing is sent.
            DeviceUnavailableError: The device could not be reached, or refused every connect
                for the whole retry window (the message then points at a restart), or broke the
                connection; the message says how many bytes were sent.
            OSError: Reading the data failed (a file or stream error, raised as it is).
        """
        job = data if isinstance(data, PrintData) else PrintData.of(data)
        pieces = job.pieces()
        try:
            first = next(pieces, None)
            if first is None:
                raise ValueError(_EMPTY_DATA)
            _check_port(port)
            return self._deliver(endpoint, port, itertools.chain((first,), pieces), total=job.size, drain=drain)
        finally:
            pieces.close()

    def _deliver(
        self,
        endpoint: DeviceEndpoint,
        port: int,
        pieces: Iterable[Piece],
        *,
        total: int | None,
        drain: LinkDrain | None,
    ) -> int:
        address = f"{endpoint.host}:{port}"
        carried = _DrainClock(drain, self._clock)
        with _connect(endpoint.host, port, endpoint.timeout) as sock:
            sent = _transmit(sock, pieces, address=address, total=total, carried=carried)
            wait = carried.remaining()
            if wait > 0:
                self._sleep(wait)
            _finish(sock, address=address, total=sent)
        return sent

    def accepts_connection(self, endpoint: DeviceEndpoint, port: int) -> bool:
        """Whether ``port`` accepts a connection; the connection is closed at once, with no data.

        A refused connect is retried for up to 3 s (never longer than ``timeout``), because the
        port refuses for a moment after any job closed; only a refusal that outlasts that
        window answers False. A PS301 refuses a second connection outright while a client holds
        the port, and accepts one while the port is stuck on a lost job (measured, FW 6022).

        Raises:
            ValueError: ``port`` is outside 1..65535.
            DeviceUnavailableError: The device could not be reached for another reason.
        """
        _check_port(port)
        try:
            sock = connect_retrying_refusals(endpoint.host, port, endpoint.timeout)
        except ConnectionRefusedError:
            return False
        except (OSError, UnicodeError) as exc:
            # UnicodeError: the IDNA codec refuses a malformed host name before any socket exists.
            raise DeviceUnavailableError(f"{endpoint.host}:{port} could not be reached: {exc}") from exc
        sock.close()
        return True


__all__ = ["RawPrinter", "connect_retrying_refusals"]
