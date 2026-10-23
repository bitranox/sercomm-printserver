"""A loopback LPD server for the adapter tests: records every byte, acknowledges as configured.

It speaks just enough RFC 1179 to drive a client through one exchange on one connection: a
queue-state command (0x03/0x04) gets the configured text and a close; a receive-job command
(0x02) gets an acknowledgement per step, where the steps are numbered

    0 receive-job command, 1 data file header, 2 data file, 3 control file header, 4 control file

(for a client that sends the data file first). Each step's acknowledgement is configurable: a
non-zero byte makes the client abort, an empty one makes the server close instead of answering.
"""

from __future__ import annotations

import socket
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType

_JOIN_TIMEOUT = 10.0


class _Recorder:
    """Reads from the connection and keeps a copy of every byte read."""

    def __init__(self, conn: socket.socket, sink: bytearray) -> None:
        self._conn = conn
        self._sink = sink
        self._pending = bytearray()

    def _fill(self) -> bool:
        block = self._conn.recv(65536)
        self._sink += block
        self._pending += block
        return bool(block)

    def readline(self) -> bytes:
        """Return one LF-terminated line, or what is left when the client closes."""
        while b"\n" not in self._pending:
            if not self._fill():
                return self._take(len(self._pending))
        return self._take(self._pending.index(b"\n") + 1)

    def read_exact(self, size: int) -> bytes:
        """Return ``size`` bytes, or fewer when the client closes first."""
        while len(self._pending) < size and self._fill():
            pass
        return self._take(min(size, len(self._pending)))

    def drain(self) -> None:
        """Read until the client closes."""
        while self._fill():
            pass

    def _take(self, size: int) -> bytes:
        taken = bytes(self._pending[:size])
        del self._pending[:size]
        return taken


class FakeLpdServer:
    """One-connection LPD server on 127.0.0.1, run in a thread as a context manager.

    Args:
        acks: Acknowledgement per step number (see module docstring); a missing step gets 0x00,
            ``b""`` closes the connection instead of answering.
        queue_reply: Bytes sent back for a queue-state command.
        silent: Never answer anything; just record until the client gives up and closes.
        hang_up_before_data: Acknowledge the first file header, then close without reading
            the file, so a client still sending it hits a reset.

    Attributes:
        received: Every byte the client sent, in order; complete once ``finished`` is set.
        finished: Set when the connection has ended (or the server was stopped unused).
    """

    def __init__(
        self,
        *,
        acks: Mapping[int, bytes] | None = None,
        queue_reply: bytes = b"",
        silent: bool = False,
        hang_up_before_data: bool = False,
    ) -> None:
        self._acks = dict(acks or {})
        self._hang_up_before_data = hang_up_before_data
        self._queue_reply = queue_reply
        self._silent = silent
        self._listener = socket.create_server(("127.0.0.1", 0))
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self.received = bytearray()
        self.finished = threading.Event()
        self.accepted = False

    @property
    def port(self) -> int:
        """The TCP port the server listens on."""
        return int(self._listener.getsockname()[1])

    def __enter__(self) -> FakeLpdServer:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._listener.close()
        self._thread.join(_JOIN_TIMEOUT)

    def _serve(self) -> None:
        try:
            conn, _ = self._listener.accept()
        except OSError:
            self.finished.set()
            return
        self.accepted = True
        try:
            with conn:
                self._session(conn, _Recorder(conn, self.received))
        finally:
            self.finished.set()

    def _session(self, conn: socket.socket, reader: _Recorder) -> None:
        command = reader.readline()
        if not command:
            return
        if self._silent:
            reader.drain()
            return
        if command[:1] in (b"\x03", b"\x04"):
            conn.sendall(self._queue_reply)
            return
        self._receive_job(conn, reader)

    def _receive_job(self, conn: socket.socket, reader: _Recorder) -> None:
        step = 0
        if not self._ack(conn, step):
            return
        while subcommand := reader.readline():
            step += 1
            if not self._ack(conn, step) or self._hang_up_before_data:
                return
            count = int(subcommand[1:].split(b" ", 1)[0])
            reader.read_exact(count + 1)
            step += 1
            if not self._ack(conn, step):
                return

    def _ack(self, conn: socket.socket, step: int) -> bool:
        """Send the step's acknowledgement; return whether the exchange goes on."""
        ack = self._acks.get(step, b"\x00")
        if ack:
            conn.sendall(ack)
        return ack == b"\x00"


def closed_port() -> int:
    """Return a loopback port nothing listens on (bound, then released)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


__all__ = ["FakeLpdServer", "closed_port"]
