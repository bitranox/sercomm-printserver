"""A loopback FTP server speaking the SerComm print server's dialect, for adapter tests.

It mirrors what a PS301 (firmware 6022) was measured to do: banner ``220 Print Server Ready.``,
``215`` for ``SYST``/``HELP``, ``500 Invalid command.`` for ``PASV``, ``PWD``, ``NOOP`` and every
other unknown verb, active-mode data connections only (it connects back to the ``PORT`` address),
and one connection at a time.

It is deterministic by construction: it reserves its port in the constructor and binds and
listens only when told to, so a test can make connects fail with ECONNREFUSED and then let one
through without any sleep. Nothing is bound while it refuses: a socket that is bound but not
listening makes Linux and Windows answer a connect with RST, but macOS leaves the SYN unanswered
until the client times out, and a real device that is not listening has nothing bound either.
"""

from __future__ import annotations

import contextlib
import socket
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType

#: Actions the device performs on ``RETR``; the fake answers them with an empty transfer.
DEVICE_ACTIONS = frozenset({"RESET", "DEFAULTC", "PASSRESET", "SETIP"})

#: Upper bound for any single blocking socket call in the fake, so a broken test fails instead
#: of hanging the run. It is never waited out in a passing test.
_SAFETY_TIMEOUT = 10.0


@dataclass(frozen=True)
class FakeFtpBehaviour:
    """How the fake device behaves.

    Attributes:
        files: Contents served by ``RETR``.
        credentials: ``(user, password)`` the fake requires before ``RETR``/``STOR``; None means
            no login is needed.
        echo_password_on_refusal: Put the received password into the 530 reply, to prove the
            client never repeats it.
        drop_after: Verb after which the control connection is closed without any reply.
        replies: Fixed reply per verb, replacing the normal handling.
        banner: The greeting sent on connect.
        send_banner: False makes the fake accept and then stay silent.
    """

    files: Mapping[str, bytes] = field(default_factory=lambda: {})
    credentials: tuple[str, str] | None = None
    echo_password_on_refusal: bool = False
    drop_after: str | None = None
    replies: Mapping[str, str] = field(default_factory=lambda: {})
    banner: str = "220 Print Server Ready."
    send_banner: bool = True


class _Session:
    """State of one control connection."""

    def __init__(self, conn: socket.socket) -> None:
        self.conn = conn
        self.reader = conn.makefile("rb")
        self.user = ""
        self.logged_in = False
        self.data_address: tuple[str, int] | None = None

    def reply(self, line: str) -> None:
        self.conn.sendall(line.encode("latin-1") + b"\r\n")


class FakeFtpServer:
    """Threaded single-connection FTP server on 127.0.0.1.

    Args:
        behaviour: How the fake device behaves.
        listening: False reserves the port but refuses connects until ``begin_listening``.
    """

    def __init__(self, behaviour: FakeFtpBehaviour, *, listening: bool = True) -> None:
        self.behaviour = behaviour
        self.commands: list[str] = []
        self.uploads: dict[str, bytes] = {}
        self.sessions = 0
        self._stopping = threading.Event()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self.port: int = self._listener.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, name="fake-ftp", daemon=True)
        self._listening = False
        if listening:
            self.begin_listening()
        else:
            # Release the port and keep only its number until begin_listening binds it again.
            self._listener.close()

    def begin_listening(self) -> None:
        """Start accepting connections; until then a connect is refused."""
        if self._listening:
            return
        if self._listener.fileno() == -1:
            self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._listener.bind(("127.0.0.1", self.port))
        self._listening = True
        self._listener.listen(4)
        self._thread.start()

    def stop(self) -> None:
        """Stop the server thread and release the port."""
        if self._listening:
            self._stopping.set()
            # accept() does not wake on close(); a throwaway connect lets the thread see the flag.
            with socket.create_connection(("127.0.0.1", self.port), timeout=_SAFETY_TIMEOUT):
                pass
            self._thread.join(_SAFETY_TIMEOUT)
        self._listener.close()

    def __enter__(self) -> FakeFtpServer:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    def _serve(self) -> None:
        while True:
            conn, _address = self._listener.accept()
            with conn:
                if self._stopping.is_set():
                    return
                conn.settimeout(_SAFETY_TIMEOUT)
                self.sessions += 1
                # A client that resets the connection ends only its own session, as on the device.
                with contextlib.suppress(OSError):
                    self._handle(_Session(conn))

    def _handle(self, session: _Session) -> None:
        if not self.behaviour.send_banner:
            # Stay silent until the client gives up and closes.
            while session.conn.recv(1024):
                pass
            return
        session.reply(self.behaviour.banner)
        while True:
            raw = session.reader.readline()
            if not raw:
                return
            line = raw.decode("latin-1").rstrip("\r\n")
            self.commands.append(line)
            verb, _, argument = line.partition(" ")
            verb = verb.upper()
            if verb == self.behaviour.drop_after:
                return
            if not self._answer(session, verb, argument):
                return

    def _answer(self, session: _Session, verb: str, argument: str) -> bool:
        """Answer one command; return False when the session ends."""
        fixed = self.behaviour.replies.get(verb)
        if fixed is not None:
            session.reply(fixed)
            return True
        if verb == "QUIT":
            session.reply("221 Goodbye.")
            return False
        handler = {
            "USER": self._user,
            "PASS": self._pass,
            "SYST": self._system,
            "HELP": self._system,
            "TYPE": self._type,
            "PORT": self._port,
            "RETR": self._retrieve,
            "STOR": self._store,
        }.get(verb, self._invalid)
        handler(session, argument)
        return True

    @staticmethod
    def _invalid(session: _Session, _argument: str) -> None:
        session.reply("500 Invalid command.")

    @staticmethod
    def _system(session: _Session, _argument: str) -> None:
        session.reply("215 Print Server FW 6022")

    @staticmethod
    def _type(session: _Session, _argument: str) -> None:
        session.reply("200 Command OK.")

    @staticmethod
    def _user(session: _Session, argument: str) -> None:
        session.user = argument
        session.reply("331 Password required.")

    def _pass(self, session: _Session, argument: str) -> None:
        expected = self.behaviour.credentials
        if expected is None or (session.user, argument) == expected:
            session.logged_in = True
            session.reply("230 User logged in.")
            return
        echo = f" for password {argument}" if self.behaviour.echo_password_on_refusal else ""
        session.reply(f"530 Login incorrect{echo}.")

    @staticmethod
    def _port(session: _Session, argument: str) -> None:
        parts = [int(part) for part in argument.split(",")]
        session.data_address = (".".join(str(part) for part in parts[:4]), parts[4] * 256 + parts[5])
        session.reply("200 Command OK.")

    def _authorised(self, session: _Session) -> bool:
        if self.behaviour.credentials is None or session.logged_in:
            return True
        session.reply("530 Not logged in.")
        return False

    def _retrieve(self, session: _Session, argument: str) -> None:
        if not self._authorised(session):
            return
        name = argument.upper()
        if name in self.behaviour.files:
            payload = self.behaviour.files[name]
        elif name in DEVICE_ACTIONS:
            payload = b""
        else:
            session.reply("550 File not found.")
            return
        session.reply("150 Opening data connection.")
        with self._data_connection(session) as data:
            data.sendall(payload)
        session.reply("226 Transfer complete.")

    def _store(self, session: _Session, argument: str) -> None:
        if not self._authorised(session):
            return
        session.reply("150 Opening data connection.")
        received = bytearray()
        with self._data_connection(session) as data:
            while chunk := data.recv(65536):
                received.extend(chunk)
        self.uploads[argument] = bytes(received)
        session.reply("226 Transfer complete.")

    @staticmethod
    def _data_connection(session: _Session) -> socket.socket:
        if session.data_address is None:
            msg = "RETR/STOR without PORT: the client is not in active mode"
            raise AssertionError(msg)
        return socket.create_connection(session.data_address, timeout=_SAFETY_TIMEOUT)


def closed_port() -> int:
    """Return a loopback port that nothing listens on.

    Returns:
        A port number that was free a moment ago.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


__all__ = ["DEVICE_ACTIONS", "FakeFtpBehaviour", "FakeFtpServer", "closed_port"]
