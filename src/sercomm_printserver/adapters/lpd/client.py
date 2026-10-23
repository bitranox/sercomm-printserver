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
"""

from __future__ import annotations

import re
import secrets
import socket
from typing import TYPE_CHECKING, Final

from ...domain.errors import DeviceResponseError, DeviceUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from ...domain.endpoint import DeviceEndpoint, PrintJob

#: A queue name as RFC 1179 puts it on the wire: printable ASCII without spaces, short enough for
#: any LPD implementation's queue table.
_QUEUE_NAME: Final = re.compile(r"[\x21-\x7e]{1,31}")
#: Print data is written in slices of this size so a large job is never copied as a whole.
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

    def send(self, data: bytes | memoryview, *, step: str) -> None:
        """Send ``data`` completely; callers pass pieces of at most ``_CHUNK`` bytes.

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

    def expect_ack(self, step: str) -> None:
        """Read the one-byte acknowledgement of ``step``.

        Raises:
            DeviceUnavailableError: No byte arrived before the device had answered anything.
            DeviceResponseError: The acknowledgement is not 0x00, or the connection ended after
                an earlier answer.
        """
        reply = self._recv(1, step=step)
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

    def _recv(self, size: int, *, step: str) -> bytes:
        try:
            return self._sock.recv(size)
        except OSError as exc:
            raise self._lost(step, f"{exc} while waiting for the reply") from exc

    def _lost(self, step: str, detail: str) -> DeviceUnavailableError | DeviceResponseError:
        if self._answered:
            return DeviceResponseError(f"{self._address} broke off during the {step}: {detail}")
        return DeviceUnavailableError(f"{self._address} did not answer the {step}: {detail}")


def _send_file(conn: _LpdConnection, *, subcommand: bytes, name: str, content: bytes, label: str) -> None:
    """Send one file of a job: header line, ack, content, the 0x00 terminator, ack."""
    conn.send(subcommand + f"{len(content)} {name}\n".encode("ascii"), step=f"{label} header")
    conn.expect_ack(f"{label} header")
    view = memoryview(content)
    for start in range(0, len(view), _CHUNK):
        conn.send(view[start : start + _CHUNK], step=label)
    conn.send(b"\x00", step=label)
    conn.expect_ack(label)


class LpdClient:
    """Implements ``LpdPort`` over RFC 1179, one connection per call.

    Args:
        job_number: Source of the three-digit job number in the file names (``dfA<nnn>host``);
            tests inject a fixed one. Defaults to a random number 0-999.

    Example:
        >>> client = LpdClient(job_number=lambda: 7)
        >>> client.queue_state.__name__
        'queue_state'
    """

    def __init__(self, *, job_number: Callable[[], int] = _random_job_number) -> None:
        self._job_number = job_number

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

    def submit(self, endpoint: DeviceEndpoint, queue: str, job: PrintJob) -> None:
        """Send one print job to ``queue``: receive-job command, data file, then control file.

        Args:
            endpoint: The print server.
            queue: Logical printer, ``L1``..``L8`` or ``lp``.
            job: The data plus the names for the control file.

        Raises:
            ValueError: Invalid queue name, empty job data, or a job number outside 0-999;
                nothing was sent.
            DeviceUnavailableError: The device could not be reached or did not answer.
            DeviceResponseError: A step was acknowledged with a non-zero byte (the message names
                the step) or the device broke off the exchange.
        """
        queue_name = _queue_bytes(queue)
        if not job.data:
            raise ValueError("an LPD print job needs at least one byte of data")
        tag = _job_tag(self._job_number())
        data_name = f"dfA{tag}{job.client_host}"
        control = _control_file(job, data_name)
        with _LpdConnection(endpoint) as conn:
            conn.send(b"\x02" + queue_name + b"\n", step="receive-job command")
            conn.expect_ack("receive-job command")
            _send_file(conn, subcommand=b"\x03", name=data_name, content=job.data, label="data file")
            _send_file(
                conn, subcommand=b"\x02", name=f"cfA{tag}{job.client_host}", content=control, label="control file"
            )


__all__ = ["LpdClient"]
