"""TFTP (RFC 1350) client for the print server's virtual files, read-only.

Why it exists: the vendor manual (TE-310 twin) says ``tftp <ip> GET RESET`` restarts the
device and ``tftp <ip> GET DEFAULTC`` restores factory defaults without any login, and that
``CONFIG`` and ``PSINF`` can be read the same way. That is the recovery path when the FTP
password is unknown. None of it has been measured on a PS301; this firmware may not run a TFTP
server at all, in which case every call ends in ``DeviceUnavailableError``.

Protocol choices:

* Octet mode only: the files are byte-exact device data, netascii would rewrite line ends.
* The server answers from a new port (its transfer ID); the client locks onto the address of the
  first reply and answers packets from any other address with ERROR 5, as RFC 1350 requires.
* On timeout the last packet is sent again, three times at most, so a lost datagram does not
  fail the call; the timeout itself is ``endpoint.timeout``.
* A transfer is capped at 1 MiB; the device's files are a few KiB.
"""

from __future__ import annotations

import contextlib
import socket
import struct
from enum import Enum
from typing import TYPE_CHECKING, Final, NamedTuple

from ...domain.errors import DeviceResponseError, DeviceUnavailableError

if TYPE_CHECKING:
    from ...domain.device_files import DeviceAction, ReadableFile
    from ...domain.endpoint import DeviceEndpoint

_OP_RRQ: Final = 1
_OP_DATA: Final = 3
_OP_ACK: Final = 4
_OP_ERROR: Final = 5
_ERR_DISK_FULL: Final = 3
_ERR_UNKNOWN_TID: Final = 5
#: Opcode plus block number or error code: the fixed head of every packet but RRQ.
_HEAD: Final = 4
_BLOCK: Final = 512
_RETRANSMITS: Final = 3
_SIZE_CAP: Final = 1024 * 1024
#: Large enough for any UDP datagram, so an oversized DATA block is seen whole and refused.
_RECV_SIZE: Final = 65536
_QUOTE_LIMIT: Final = 80

_Address = tuple[object, ...]


class _Received(NamedTuple):
    """What a transfer delivered and whether it ended with a short block."""

    data: bytes
    complete: bool


class _Step(Enum):
    """How one received DATA packet moved the transfer."""

    NEW_BLOCK = "new block"
    DUPLICATE = "duplicate"
    LAST_BLOCK = "last block"


def _packet(opcode: int, number: int, payload: bytes = b"") -> bytes:
    return struct.pack("!HH", opcode, number) + payload


def _read_request(filename: str) -> bytes:
    return struct.pack("!H", _OP_RRQ) + filename.encode("ascii") + b"\x00octet\x00"


def _error_packet(code: int, message: str) -> bytes:
    return _packet(_OP_ERROR, code, message.encode("ascii") + b"\x00")


def _quote(raw: bytes) -> str:
    """Return a device message for an exception text: NUL-terminated, ASCII, truncated."""
    text = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return repr(text[:_QUOTE_LIMIT])


class _Transfer:
    """One read transfer over one UDP socket; knows whether the server has answered yet."""

    def __init__(self, sock: socket.socket, server: _Address, label: str) -> None:
        self._sock = sock
        self._label = label
        self._dest = server
        self._tid: _Address | None = None
        self._last = b""
        self._expected = 1
        self._data = bytearray()

    def run(self, request: bytes) -> _Received:
        """Send ``request`` and receive DATA until a short block or the retries run out."""
        self._send(request)
        retries = 0
        while True:
            packet = self._receive()
            if packet is None:
                if retries == _RETRANSMITS:
                    return self._gave_up()
                retries += 1
                self._send(self._last)
                continue
            step = self._handle(packet)
            if step is _Step.LAST_BLOCK:
                return _Received(bytes(self._data), complete=True)
            if step is _Step.NEW_BLOCK:
                retries = 0

    def _gave_up(self) -> _Received:
        if self._tid is None:
            raise DeviceUnavailableError(
                f"{self._label} did not answer the TFTP request after {_RETRANSMITS} retransmissions"
            )
        return _Received(bytes(self._data), complete=False)

    def _receive(self) -> bytes | None:
        """Return the next packet from the transfer partner, or None on timeout."""
        while True:
            try:
                packet, sender = self._sock.recvfrom(_RECV_SIZE)
            except TimeoutError:
                return None
            except OSError as exc:
                raise self._lost(str(exc)) from exc
            if self._tid is None:
                self._tid = sender
                self._dest = sender
            if sender == self._tid:
                return packet
            # Another address joined the exchange; RFC 1350 says tell it, then carry on.
            with contextlib.suppress(OSError):
                self._sock.sendto(_error_packet(_ERR_UNKNOWN_TID, "Unknown transfer ID"), sender)

    def _handle(self, packet: bytes) -> _Step:
        if len(packet) < _HEAD:
            raise DeviceResponseError(f"{self._label} sent a malformed TFTP packet {packet[:20]!r}")
        opcode, number = struct.unpack("!HH", packet[:_HEAD])
        if opcode == _OP_ERROR:
            raise DeviceResponseError(f"{self._label} answered TFTP error {number}: {_quote(packet[_HEAD:])}")
        if opcode != _OP_DATA:
            raise DeviceResponseError(f"{self._label} sent TFTP opcode {opcode} where DATA was expected")
        return self._accept(number, packet[_HEAD:])

    def _accept(self, number: int, payload: bytes) -> _Step:
        if number != self._expected:
            # The previous block again means our ACK was lost: acknowledge it once more.
            if self._expected > 1 and number == self._expected - 1:
                self._send(self._last)
            return _Step.DUPLICATE
        if len(payload) > _BLOCK:
            raise DeviceResponseError(f"{self._label} sent a {len(payload)}-byte TFTP block, at most {_BLOCK} allowed")
        self._data += payload
        if len(self._data) > _SIZE_CAP:
            with contextlib.suppress(OSError):
                self._sock.sendto(_error_packet(_ERR_DISK_FULL, "File too large"), self._dest)
            raise DeviceResponseError(f"{self._label} sent more than {_SIZE_CAP} bytes over TFTP")
        self._send(_packet(_OP_ACK, number))
        self._expected = number + 1
        return _Step.LAST_BLOCK if len(payload) < _BLOCK else _Step.NEW_BLOCK

    def _send(self, packet: bytes) -> None:
        try:
            self._sock.sendto(packet, self._dest)
        except OSError as exc:
            raise self._lost(str(exc)) from exc
        self._last = packet

    def _lost(self, detail: str) -> DeviceUnavailableError | DeviceResponseError:
        if self._tid is None:
            return DeviceUnavailableError(f"{self._label} could not be reached over TFTP: {detail}")
        return DeviceResponseError(f"{self._label} broke off the TFTP transfer: {detail}")


def _request(endpoint: DeviceEndpoint, filename: str) -> _Received:
    """Run one read request for ``filename`` on a fresh socket."""
    label = f"{endpoint.host}:{endpoint.tftp_port}"
    try:
        addresses = socket.getaddrinfo(endpoint.host, endpoint.tftp_port, type=socket.SOCK_DGRAM)
        family, kind, proto, _, server = addresses[0]
        sock = socket.socket(family, kind, proto)
    except OSError as exc:
        raise DeviceUnavailableError(f"{label} could not be reached over TFTP: {exc}") from exc
    with sock:
        sock.settimeout(endpoint.timeout)
        return _Transfer(sock, server, label).run(_read_request(filename))


class TftpClient:
    """Implements ``TftpPort`` over RFC 1350, octet mode, one socket per call.

    Per the vendor manual and unverified on hardware: reads need no login, and a read of an
    action file triggers the action.

    Example:
        >>> TftpClient().retrieve.__name__
        'retrieve'
    """

    def retrieve(self, endpoint: DeviceEndpoint, name: ReadableFile) -> bytes:
        """Return the bytes of a readable virtual file.

        Args:
            endpoint: The print server; ``tftp_port`` and ``timeout`` are used.
            name: The file to read.

        Returns:
            The file content.

        Raises:
            DeviceUnavailableError: No reply after three retransmissions, or no route.
            DeviceResponseError: An ERROR packet (quoted), a malformed packet, more than 1 MiB,
                or the transfer stopped before its short last block.
        """
        received = _request(endpoint, name.value)
        if not received.complete:
            raise DeviceResponseError(
                f"{endpoint.host}:{endpoint.tftp_port} stopped the TFTP transfer of {name.value} "
                f"after {len(received.data)} bytes"
            )
        return received.data

    def trigger(self, endpoint: DeviceEndpoint, action: DeviceAction) -> None:
        """Trigger an action by requesting its file.

        Any DATA counts as success and is consumed to the end; a transfer that stops after DATA
        has arrived also counts, since the device may restart mid-transfer. A device that
        restarts before answering at all is indistinguishable from an absent one and reports
        ``DeviceUnavailableError`` (per manual, unverified on hardware).

        Args:
            endpoint: The print server; ``tftp_port`` and ``timeout`` are used.
            action: The action file to request.

        Raises:
            DeviceUnavailableError: No reply after three retransmissions, or no route.
            DeviceResponseError: An ERROR packet (quoted), a malformed packet, or more than 1 MiB.
        """
        _request(endpoint, action.value)


__all__ = ["TftpClient"]
