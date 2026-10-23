"""A loopback TFTP server for the adapter tests: answers from a new port, records every packet.

Like a real RFC 1350 server it receives read requests on its well-known socket and runs each
transfer from a fresh ephemeral port (its transfer ID). The behaviour knobs reproduce what a
client must cope with: an ERROR or malformed reply, silence, a lost DATA block, a transfer that stops
midway, and a stranger sending a packet into the transfer.

The server stops when the test leaves the ``with`` block: a sentinel datagram queued behind any
retransmitted requests, so every packet the client sent is recorded before the thread ends.
"""

from __future__ import annotations

import socket
import struct
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType

_STOP = b"STOP"
_BLOCK = 512
#: How long the server waits for an ACK before abandoning a transfer; only reached when the
#: client gave up, so it never paces a passing test.
_ACK_WAIT = 5.0
_JOIN_TIMEOUT = 10.0


def data_packet(number: int, payload: bytes) -> bytes:
    """Return a DATA packet."""
    return struct.pack("!HH", 3, number) + payload


def ack_packet(number: int) -> bytes:
    """Return an ACK packet."""
    return struct.pack("!HH", 4, number)


def error_packet(code: int, message: bytes) -> bytes:
    """Return an ERROR packet."""
    return struct.pack("!HH", 5, code) + message + b"\x00"


def split_blocks(content: bytes) -> list[bytes]:
    """Split ``content`` into DATA payloads, ending with a short (possibly empty) block."""
    blocks = [content[start : start + _BLOCK] for start in range(0, len(content), _BLOCK)]
    if not blocks or len(blocks[-1]) == _BLOCK:
        blocks.append(b"")
    return blocks


class FakeTftpServer:
    """TFTP server on 127.0.0.1 run in a thread as a context manager.

    Args:
        content: The bytes every read request is served.
        raw_reply: Answer each request with these bytes (an ERROR packet, a malformed or
            oversized one) from the transfer port instead of serving ``content``.
        silent: Record requests, never answer.
        drop_block: Do not send this block the first time; for block 1 the first request is
            ignored, later blocks are sent when the client retransmits its previous ACK.
        stop_after_blocks: Send this many blocks, then go quiet.
        stray_after_block: After sending this block, send a DATA packet to the client from a
            third port and record what the client answers there.

    Attributes:
        requests: Every datagram that reached the well-known port, in order.
        transfer_packets: Every datagram the client sent to the transfer port, in order.
        stray_reply: What the client sent back to the stray port, or None.
    """

    def __init__(
        self,
        *,
        content: bytes = b"",
        raw_reply: bytes | None = None,
        silent: bool = False,
        drop_block: int | None = None,
        stop_after_blocks: int | None = None,
        stray_after_block: int | None = None,
    ) -> None:
        self._content = content
        self._raw_reply = raw_reply
        self._silent = silent
        self._drop_block = drop_block
        self._stop_after = stop_after_blocks
        self._stray_after = stray_after_block
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", 0))
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self.requests: list[bytes] = []
        self.transfer_packets: list[bytes] = []
        self.stray_reply: bytes | None = None

    @property
    def port(self) -> int:
        """The well-known port read requests go to."""
        return int(self._sock.getsockname()[1])

    def __enter__(self) -> FakeTftpServer:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stopper:
            stopper.sendto(_STOP, ("127.0.0.1", self.port))
        self._thread.join(_JOIN_TIMEOUT)
        self._sock.close()

    def _serve(self) -> None:
        while True:
            request, client = self._sock.recvfrom(65536)
            if request == _STOP:
                return
            self.requests.append(request)
            if self._silent or (self._drop_block == 1 and len(self.requests) == 1):
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as transfer:
                transfer.bind(("127.0.0.1", 0))
                transfer.settimeout(_ACK_WAIT)
                self._transfer(transfer, client)

    def _transfer(self, transfer: socket.socket, client: tuple[str, int]) -> None:
        if self._raw_reply is not None:
            transfer.sendto(self._raw_reply, client)
            return
        for number, payload in enumerate(split_blocks(self._content), start=1):
            if self._stop_after is not None and number > self._stop_after:
                return
            packet = data_packet(number, payload)
            # Block 1 was "lost" by ignoring the first request; later blocks are lost here.
            if number == 1 or number != self._drop_block:
                transfer.sendto(packet, client)
            if number == self._stray_after:
                self._send_stray(client, number)
            if not self._await_ack(transfer, number, packet, client):
                return

    def _await_ack(self, transfer: socket.socket, number: int, packet: bytes, client: tuple[str, int]) -> bool:
        """Wait for the ACK of ``number``; resend on the client's retransmitted previous ACK."""
        while True:
            try:
                reply, _ = transfer.recvfrom(65536)
            except TimeoutError:
                return False
            self.transfer_packets.append(reply)
            if reply == ack_packet(number):
                return True
            if reply == ack_packet(number - 1):
                transfer.sendto(packet, client)
                continue
            return False

    def _send_stray(self, client: tuple[str, int], number: int) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stray:
            stray.bind(("127.0.0.1", 0))
            stray.settimeout(_ACK_WAIT)
            stray.sendto(data_packet(number + 1, b"intruder"), client)
            self.stray_reply, _ = stray.recvfrom(65536)


__all__ = ["FakeTftpServer", "ack_packet", "data_packet", "error_packet", "split_blocks"]
