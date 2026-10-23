"""A loopback Telnet server speaking the PS301's console dialect, for adapter tests.

It sends the greeting measured on a real PS301 (firmware 6022), records every byte the client
sends, and on ``monitor``/``exit`` echoes the command lines, prints the monitor blocks and
closes, as the device does. Other behaviours reproduce the failures the client must survive.
Waiting is done with ``select`` on the connection plus a wake-up socket, so no test sleeps.
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

#: Exactly what the PS301 sent on connect: IAC WILL ECHO, IAC DO SGA, IAC WILL SGA, banner, prompt.
GREETING: Final = b"\xff\xfb\x01\xff\xfd\x03\xff\xfb\x03\r\n\r\nWelcome to Print Server\r\n\r\nPS>"
#: The monitor blocks the PS301 printed while idle, after its echo of the command lines.
IDLE_MONITOR: Final = (
    b"\r\n(P1)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n\r\n"
    b"(P2)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n\r\n"
    b"(SP)STATE: Idle\r\nTYPE: Serial\r\nPRINTER STATUS: Offline\r\n\r\n"
)
_EXIT_LINE: Final = b"exit\r\n"
_GUARD_SECONDS: Final = 10.0
_RECV_SIZE: Final = 4096


class TelnetBehaviour(Enum):
    """How the fake device answers."""

    DEVICE = "device"
    NO_PROMPT = "no-prompt"
    PROMPT_THEN_HANG = "prompt-then-hang"
    OVERSIZED = "oversized"
    CLOSE_BEFORE_PROMPT = "close-before-prompt"
    RESET_BEFORE_PROMPT = "reset-before-prompt"


class FakeTelnetServer:
    """One-connection Telnet server on 127.0.0.1; use as a context manager."""

    def __init__(
        self,
        *,
        behaviour: TelnetBehaviour = TelnetBehaviour.DEVICE,
        monitor_output: bytes = IDLE_MONITOR,
        oversized_bytes: int = 128 * 1024,
    ) -> None:
        self._behaviour = behaviour
        self._monitor_output = monitor_output
        self._oversized_bytes = oversized_bytes
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port: int = self._listener.getsockname()[1]
        self._wake_reader, self._wake_writer = socket.socketpair()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.received = bytearray()
        self.connections = 0

    def __enter__(self) -> FakeTelnetServer:
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
            raise AssertionError("fake Telnet server did not finish")

    def _run(self) -> None:
        readable, _, _ = select.select([self._listener, self._wake_reader], [], [], _GUARD_SECONDS)
        if self._listener not in readable:
            return
        conn, _ = self._listener.accept()
        self.connections += 1
        with conn:
            self._serve(conn)

    def _serve(self, conn: socket.socket) -> None:
        if self._behaviour is TelnetBehaviour.RESET_BEFORE_PROMPT:
            # Linger 0 makes close() send RST instead of FIN: a connection dropped mid-session.
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            return
        if self._behaviour is TelnetBehaviour.CLOSE_BEFORE_PROMPT:
            conn.sendall(GREETING.removesuffix(b"PS>"))
            return
        if self._behaviour is TelnetBehaviour.NO_PROMPT:
            conn.sendall(GREETING.removesuffix(b"PS>"))
            self._hold(conn)
            return
        conn.sendall(GREETING)
        if self._behaviour is TelnetBehaviour.PROMPT_THEN_HANG:
            self._hold(conn)
            return
        self._read_command(conn)
        if _EXIT_LINE not in self.received:
            return  # the client gave up before sending the command; nothing to answer
        if self._behaviour is TelnetBehaviour.OVERSIZED:
            self._flood(conn)
            self._hold(conn)
            return
        conn.sendall(bytes(self.received) + self._monitor_output)

    def _read_command(self, conn: socket.socket) -> None:
        while _EXIT_LINE not in self.received:
            data = conn.recv(_RECV_SIZE)
            if not data:
                return
            self.received += data

    def _flood(self, conn: socket.socket) -> None:
        try:
            conn.sendall(b"A" * self._oversized_bytes)
        except OSError:
            return  # the client stopped reading at its cap and closed; that is the point

    def _hold(self, conn: socket.socket) -> None:
        """Keep the connection open, recording input, until the client closes or the test ends."""
        while True:
            readable, _, _ = select.select([conn, self._wake_reader], [], [], _GUARD_SECONDS)
            if conn not in readable:
                return
            try:
                data = conn.recv(_RECV_SIZE)
            except OSError:
                return
            if not data:
                return
            self.received += data


__all__ = ["GREETING", "IDLE_MONITOR", "FakeTelnetServer", "TelnetBehaviour"]
