"""LPD (RFC 1179) client for the print server's queues ``L1``..``L8`` and ``lp``.

Why it is shaped this way:

* The vendor manual says the device prints the data file the moment it arrives and ignores the
  options in the control file, and that most LPD clients send the data file first. This client
  therefore sends the data file before the control file and puts only identifying lines into the
  control file.
* RFC 1179 asks a client to use a source port in 721-731. Binding one needs root, so the client
  connects from an ephemeral port; a strict server could refuse that (unverified on the PS301).
* The PS301's queue-state reply has not been measured, so it is returned as text, unparsed.
* One TCP connection per call: the device serves few connections at once and keeps no session.
* The data file's header carries its size, so data of unknown size (a pipe) is first copied to
  a temporary file in pieces; data of known size is sent as it is read. Either way one piece of
  at most 64 KiB is in memory at a time. A file whose size changes while it is sent is stopped
  before its end-of-file byte, so the server discards the job rather than taking a wrong one.
"""

from __future__ import annotations

import contextlib
import re
import secrets
import socket
import tempfile
from typing import IO, TYPE_CHECKING, Final, NamedTuple

from ...domain.errors import DeviceResponseError, DeviceUnavailableError, PrintSourceChangedError, SpoolError
from ...domain.print_data import PrintData

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from ...domain.endpoint import DeviceEndpoint, PrintJob
    from ...domain.print_data import Piece

#: A queue name as RFC 1179 puts it on the wire: printable ASCII without spaces, short enough for
#: any LPD implementation's queue table.
_QUEUE_NAME: Final = re.compile(r"[\x21-\x7e]{1,31}")
#: Bytes read per call while a queue-state reply is collected.
_CHUNK: Final = 64 * 1024
#: Upper bound for a queue-state reply; a device that keeps talking past it is not answering LPD.
_STATE_CAP: Final = 64 * 1024
_ACK_OK: Final = b"\x00"
_JOB_NUMBER_LIMIT: Final = 1000


def _random_job_number() -> int:
    """Return a job number 0-999; ``secrets`` because the number need not be predictable either."""
    return secrets.randbelow(_JOB_NUMBER_LIMIT)


def _queue_bytes(queue: str) -> bytes:
    """Return the queue name as wire bytes after checking it.

    Raises:
        ValueError: The name is empty, longer than 31 characters, or has spaces, control or
            non-ASCII characters - it would corrupt the command line.
    """
    if _QUEUE_NAME.fullmatch(queue) is None:
        raise ValueError(f"LPD queue name {queue[:40]!r} is not 1-31 printable ASCII characters without spaces")
    return queue.encode("ascii")


def _job_tag(number: int) -> str:
    """Return the three-digit job number RFC 1179 puts into the file names.

    Raises:
        ValueError: ``number`` is outside 0-999.
    """
    if not 0 <= number < _JOB_NUMBER_LIMIT:
        raise ValueError(f"LPD job number {number} is outside 0-999")
    return f"{number:03d}"


def _control_file(job: PrintJob, data_name: str) -> bytes:
    """Return the control file: host, user, job name, then print and unlink the data file.

    ``l`` (print as-is, control characters kept) is used because the device receives raw printer
    language; the device ignores the line anyway (vendor manual).
    """
    lines = (
        f"H{job.client_host}",
        f"P{job.user}",
        f"J{job.name}",
        f"l{data_name}",
        f"U{data_name}",
        f"N{job.name}",
    )
    return "".join(f"{line}\n" for line in lines).encode("ascii")


class _LpdConnection:
    """One TCP connection to the LPD port that remembers whether the device has answered.

    The distinction decides the error type: silence or a reset before the first reply means the
    device is not there (``DeviceUnavailableError``); losing it later means it broke off the
    exchange (``DeviceResponseError``).
    """

    def __init__(self, endpoint: DeviceEndpoint) -> None:
        self._address = f"{endpoint.host}:{endpoint.lpd_port}"
        self._timeout = endpoint.timeout
        self._answered = False
        try:
            self._sock = socket.create_connection((endpoint.host, endpoint.lpd_port), timeout=endpoint.timeout)
        except OSError as exc:
            raise DeviceUnavailableError(f"{self._address} could not be reached: {exc}") from exc

    def __enter__(self) -> _LpdConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._sock.close()

    def send(self, data: Piece, *, step: str) -> None:
        """Send ``data`` completely; callers pass pieces of at most 64 KiB.

        The piece size is what makes the timeout bound a device that stopped reading: Windows
        accepts one send call of any size whole while its send buffer is not full, so a whole
        job handed to one ``sendall`` returns at once there and the stall would only surface
        later, as a missing acknowledgement.

        Raises:
            DeviceUnavailableError: The connection failed before the device answered anything.
            DeviceResponseError: The connection failed after the device had answered.
        """
        try:
            self._sock.sendall(data)
        except OSError as exc:
            raise self._lost(step, f"{exc} while sending") from exc

    def expect_ack(self, step: str, *, stall_hint: str = "") -> None:
        """Read the one-byte acknowledgement of ``step``.

        ``stall_hint`` is appended to the message when the device stays silent with the
        connection open; it names what the device is known to wait for at that step.

        Raises:
            DeviceUnavailableError: No byte arrived before the device had answered anything.
            DeviceResponseError: The acknowledgement is not 0x00, or the connection ended after
                an earlier answer.
        """
        reply = self._recv(1, step=step, stall_hint=stall_hint)
        if not reply:
            raise self._lost(step, "connection closed")
        self._answered = True
        if reply != _ACK_OK:
            raise DeviceResponseError(f"{self._address} refused the {step}: acknowledgement {reply!r}")

    def read_to_end(self, *, step: str) -> bytes:
        """Read until the device closes the connection, at most ``_STATE_CAP`` bytes.

        Raises:
            DeviceUnavailableError: Timeout or reset before any byte arrived.
            DeviceResponseError: The reply exceeds the cap or stopped before the device closed.
        """
        received = bytearray()
        while block := self._recv(_CHUNK, step=step):
            self._answered = True
            received += block
            if len(received) > _STATE_CAP:
                raise DeviceResponseError(f"{self._address} sent more than {_STATE_CAP} bytes for the {step}")
        return bytes(received)

    def _recv(self, size: int, *, step: str, stall_hint: str = "") -> bytes:
        try:
            return self._sock.recv(size)
        except TimeoutError as exc:
            if not self._answered:
                raise self._lost(step, f"{exc} while waiting for the reply") from exc
            # Nothing broke: the connection is open and the device is just not answering; the
            # caller's hint says what the device waits for at this step (see _DATA_FILE_STALL).
            raise DeviceResponseError(
                f"{self._address} sent no acknowledgement of the {step} within {self._timeout:g} s{stall_hint}"
            ) from exc
        except OSError as exc:
            raise self._lost(step, f"{exc} while waiting for the reply") from exc

    def _lost(self, step: str, detail: str) -> DeviceUnavailableError | DeviceResponseError:
        if self._answered:
            return DeviceResponseError(f"{self._address} broke off during the {step}: {detail}")
        return DeviceUnavailableError(f"{self._address} did not answer the {step}: {detail}")


#: Measured on a PS301: it holds back the data file's acknowledgement while no printer takes the
#: data, so a silent device at that step is a printer problem, not a network one.
_DATA_FILE_STALL: Final = "; the print server holds it back while no printer takes the data"


class _JobFile(NamedTuple):
    """One of the two files an LPD job is made of, as RFC 1179 numbers them."""

    subcommand: bytes
    label: str
    #: Appended when the device stays silent after the file's end; empty when nothing is known.
    stall_hint: str


_DATA_FILE: Final = _JobFile(b"\x03", "data file", _DATA_FILE_STALL)
_CONTROL_FILE: Final = _JobFile(b"\x02", "control file", "")


def _send_file(conn: _LpdConnection, *, kind: _JobFile, name: str, content: PrintData) -> int:
    """Send one file of a job: header line, ack, content, the 0x00 terminator, ack; return its size.

    The header announces ``content.size``. When the pieces deliver more or fewer bytes, at most
    the announced ones are sent and the 0x00 is left out: an RFC 1179 server drops a data file
    that does not end with it.

    Raises:
        PrintSourceChangedError: The content delivered a different number of bytes.
    """
    announced = content.size
    if announced is None:
        raise ValueError(f"the {kind.label} needs a known size; spool data of unknown size first")
    conn.send(kind.subcommand + f"{announced} {name}\n".encode("ascii"), step=f"{kind.label} header")
    conn.expect_ack(f"{kind.label} header")
    sent = _send_content(conn, content, announced=announced, label=kind.label)
    conn.send(b"\x00", step=kind.label)
    conn.expect_ack(kind.label, stall_hint=kind.stall_hint)
    return sent


def _send_content(conn: _LpdConnection, content: PrintData, *, announced: int, label: str) -> int:
    """Send at most ``announced`` bytes of ``content``; refuse when it delivers another count."""
    sent = 0
    pieces = content.pieces()
    try:
        for piece in pieces:
            room = announced - sent
            if len(piece) > room:
                if room:
                    conn.send(piece[:room], step=label)
                raise PrintSourceChangedError(
                    f"the {label} grew while it was sent: all {announced} announced bytes were sent and more "
                    f"followed; {_UNTERMINATED}"
                )
            conn.send(piece, step=label)
            sent += len(piece)
    finally:
        pieces.close()
    if sent < announced:
        raise PrintSourceChangedError(
            f"the {label} shrank while it was sent: it ended after {sent} of the {announced} announced bytes; "
            f"{_UNTERMINATED}"
        )
    return sent


#: What a size mismatch leaves behind, for both directions of the change.
_UNTERMINATED: Final = (
    "the file was left without its end-of-file byte, so an LPD server discards it, but this device "
    "prints data as it arrives, so part of the job may be on paper; do not resend it blindly"
)


def _spooled(data: PrintData, spool: Callable[[], IO[bytes]], stack: contextlib.ExitStack) -> PrintData:
    """Copy data of unknown size to a temporary file in pieces; return it as data of known size.

    The file is closed when ``stack`` closes. Only creating or writing the spool is a spool
    failure: an error reading the data itself propagates unchanged.

    Raises:
        SpoolError: The temporary file could not be created or written; nothing was sent.
    """
    try:
        target = stack.enter_context(spool())
    except OSError as exc:
        raise _spool_error(exc) from exc
    written = 0
    pieces = data.pieces()
    try:
        for piece in pieces:
            written += _spool_write(target, piece)
    finally:
        pieces.close()
    try:
        target.flush()
        target.seek(0)
    except OSError as exc:
        raise _spool_error(exc) from exc
    return PrintData.from_stream(target, size=written)


def _spool_write(target: IO[bytes], piece: Piece) -> int:
    try:
        return target.write(piece)
    except OSError as exc:
        raise _spool_error(exc) from exc


def _spool_error(exc: OSError) -> SpoolError:
    return SpoolError(
        f"could not copy the print data to a temporary file in {tempfile.gettempdir()} ({exc}); nothing "
        "was sent. LPD needs the size before the data, so data of unknown size is spooled first: point "
        "TMPDIR at a directory with room for the job, or print from a file instead of a pipe"
    )


class LpdClient:
    """Implements ``LpdPort`` over RFC 1179, one connection per call.

    Args:
        job_number: Source of the three-digit job number in the file names (``dfA<nnn>host``);
            tests inject a fixed one. Defaults to a random number 0-999.
        spool: Opens the temporary file data of unknown size is copied to before it is sent;
            defaults to ``tempfile.TemporaryFile``, which ``TMPDIR`` places.

    Example:
        >>> client = LpdClient(job_number=lambda: 7)
        >>> client.queue_state.__name__
        'queue_state'
    """

    def __init__(
        self,
        *,
        job_number: Callable[[], int] = _random_job_number,
        spool: Callable[[], IO[bytes]] = tempfile.TemporaryFile,
    ) -> None:
        self._job_number = job_number
        self._spool = spool

    def queue_state(self, endpoint: DeviceEndpoint, queue: str, *, long_format: bool) -> str:
        """Return the queue-state text; command 0x03 (short) or 0x04 (long); sends no print data.

        Args:
            endpoint: The print server.
            queue: Logical printer, ``L1``..``L8`` or ``lp``.
            long_format: Ask for the long listing (0x04) instead of the short one (0x03).

        Returns:
            The reply decoded as ASCII, undecodable bytes replaced; empty when the device sent
            nothing before closing.

        Raises:
            ValueError: ``queue`` is not a valid queue name; nothing was sent.
            DeviceUnavailableError: The device could not be reached or did not answer.
            DeviceResponseError: The reply exceeded 64 KiB or broke off.
        """
        command = (b"\x04" if long_format else b"\x03") + _queue_bytes(queue) + b"\n"
        with _LpdConnection(endpoint) as conn:
            conn.send(command, step="queue-state command")
            reply = conn.read_to_end(step="queue-state command")
        return reply.decode("ascii", errors="replace")

    def submit(self, endpoint: DeviceEndpoint, queue: str, job: PrintJob) -> int:
        """Send one print job to ``queue``: receive-job command, data file, then control file.

        Data of unknown size (a pipe) is copied to a temporary file first, before the device is
        contacted, because the data file's header announces its size.

        Args:
            endpoint: The print server.
            queue: Logical printer, ``L1``..``L8`` or ``lp``.
            job: The data plus the names for the control file.

        Returns:
            The size of the data file sent.

        Raises:
            ValueError: Invalid queue name, empty job data, or a job number outside 0-999;
                nothing was sent.
            SpoolError: Data of unknown size could not be copied to a temporary file; nothing
                was sent.
            PrintSourceChangedError: The data delivered more or fewer bytes than its size
                announced (a file changed while it was sent); the job was left unterminated.
            DeviceUnavailableError: The device could not be reached or did not answer.
            DeviceResponseError: A step was acknowledged with a non-zero byte (the message names
                the step) or the device broke off the exchange.
        """
        queue_name = _queue_bytes(queue)
        with contextlib.ExitStack() as stack:
            data = job.data if job.data.size is not None else _spooled(job.data, self._spool, stack)
            if not data.size:
                raise ValueError("an LPD print job needs at least one byte of data")
            tag = _job_tag(self._job_number())
            data_name = f"dfA{tag}{job.client_host}"
            control = PrintData.of(_control_file(job, data_name))
            with _LpdConnection(endpoint) as conn:
                conn.send(b"\x02" + queue_name + b"\n", step="receive-job command")
                conn.expect_ack("receive-job command")
                sent = _send_file(conn, kind=_DATA_FILE, name=data_name, content=data)
                _send_file(conn, kind=_CONTROL_FILE, name=f"cfA{tag}{job.client_host}", content=control)
        return sent


__all__ = ["LpdClient"]
