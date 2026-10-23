"""A loopback RAW / direct-socket print port, for adapter tests.

It records every byte until the client half-closes, optionally answers, then closes, as a print server's RAW port
does at the end of a job. Other behaviours reproduce a reset mid-stream and a device that never
closes its side. Waiting is done with ``select`` on the connection plus a wake-up socket, so no
test sleeps.
"""

from __future__ import annotations

import select
import socket
import struct
import threading
from enum import Enum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from types import TracebackType

_GUARD_SECONDS: Final = 10.0
_RECV_SIZE: Final = 64 * 1024


class RawBehaviour(Enum):
    """How the fake RAW port ends the job."""

    CLOSE_AT_EOF = "close-at-eof"
    RESET_MID_STREAM = "reset-mid-stream"
    NEVER_CLOSE = "never-close"


class FakeRawServer:
    """One-connection RAW port on 127.0.0.1; use as a context manager."""

    def __init__(
        self, *, behaviour: RawBehaviour = RawBehaviour.CLOSE_AT_EOF, reset_after: int = 1024, reply: bytes = b""
    ) -> None:
        self._behaviour = behaviour
        self._reset_after = reset_after
        self._reply = reply
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port: int = self._listener.getsockname()[1]
        self._wake_reader, self._wake_writer = socket.socketpair()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.received = bytearray()
        self.connections = 0
        self.saw_half_close = False

    def __enter__(self) -> FakeRawServer:
        self._thread.start()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self._wake_writer.send(b"x")
        self._thread.join(_GUARD_SECONDS)
        for sock in (self._listener, self._wake_reader, self._wake_writer):
            sock.close()
        if self._thread.is_alive():
            raise AssertionError("fake RAW server did not finish")

    def _run(self) -> None:
        readable, _, _ = select.select([self._listener, self._wake_reader], [], [], _GUARD_SECONDS)
        if self._listener not in readable:
            return
        conn, _ = self._listener.accept()
        self.connections += 1
        with conn:
            self._serve(conn)

    def _serve(self, conn: socket.socket) -> None:
        if self._behaviour is RawBehaviour.RESET_MID_STREAM:
            self._read_until(conn, self._reset_after)
            # Linger 0 makes close() send RST instead of FIN: a device dropping the job.
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            return
        self._read_until(conn, None)
        self._send_reply(conn)
        if self._behaviour is RawBehaviour.NEVER_CLOSE:
            select.select([self._wake_reader], [], [], _GUARD_SECONDS)

    def _send_reply(self, conn: socket.socket) -> None:
        """Answer after the job, as a printer returning status would."""
        try:
            conn.sendall(self._reply)
        except OSError:
            return  # the client stopped reading at its cap and closed

    def _read_until(self, conn: socket.socket, limit: int | None) -> None:
        while limit is None or len(self.received) < limit:
            data = conn.recv(_RECV_SIZE)
            if not data:
                self.saw_half_close = True
                return
            self.received += data


__all__ = ["FakeRawServer", "RawBehaviour"]
