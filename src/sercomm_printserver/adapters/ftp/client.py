"""FTP adapter for the SerComm print-server family (implements ``FtpPort``).

The device's FTP server is a small firmware dialect, not a general FTP server, and every
choice below follows from what it does (measured on a PS301, firmware 6022):

* It refuses ``PASV``, ``PWD`` and ``NOOP`` with ``500 Invalid command.``, so data transfers run
  in ACTIVE mode only (the device connects back to a port this side opens) and no command is
  ever sent as a keepalive.
* It serves one connection at a time and refuses a new TCP connect (ECONNREFUSED) for about
  0.11 s after the previous session's ``QUIT``. A refused connect is therefore retried with a
  short backoff until a 2 s deadline; any other connect failure fails at once, because a
  timeout or an unreachable host does not clear up within that window.
* ``CONFIG`` and ``PSINF`` are served without a login and carry exact line endings (LF in
  ``CONFIG``, CRLF plus a trailing form feed in ``PSINF``), so files move in binary mode and come
  back byte for byte.
* A ``get`` of an action file (``RESET``, ``DEFAULTC``, ...) triggers the action, and a restart
  may drop the control connection instead of finishing the transfer.

Each public method opens its own connection and closes it, so the client holds no state between
calls apart from the injected clock and sleep.
"""

from __future__ import annotations

import contextlib
import ftplib  # nosec B402 - the print server speaks only FTP; it offers no encrypted protocol
import io
import time
from typing import TYPE_CHECKING

from ...domain.errors import AuthenticationRequiredError, DeviceResponseError, DeviceUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from ...domain.device_files import DeviceAction, ReadableFile, WritableFile
    from ...domain.endpoint import DeviceEndpoint

#: Total time a refused connect is retried before the device counts as unavailable.
CONNECT_DEADLINE_SECONDS = 2.0
#: First wait after a refused connect; the measured refusal window is about 0.11 s.
FIRST_BACKOFF_SECONDS = 0.05
#: Longest single wait, so a device that frees up is noticed within 0.4 s.
MAX_BACKOFF_SECONDS = 0.4
#: Largest file accepted from the device. CONFIG is about 2 KB; anything near this bound is
#: not a file of this family, and the bound keeps a misbehaving peer from filling memory.
MAX_FILE_BYTES = 1024 * 1024
#: Highest code point latin-1, the control connection's encoding, can carry.
_LATIN1_MAX = 0xFF
#: Longest reply text quoted in an error message.
_REPLY_QUOTE_LIMIT = 160

#: Losing the control connection in one of these ways after ``RETR <action>`` was sent means
#: the device went down to carry the action out (a restart), not that the action failed.
_CONNECTION_LOST = (EOFError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError)


class _DeviceFTP(ftplib.FTP):
    """``ftplib.FTP`` that remembers the verb of the last command it managed to send.

    ``trigger`` needs to know whether a dropped connection came before or after the ``RETR``
    reached the device; only the verb is kept, so a ``PASS`` line never lingers in memory here.
    """

    last_verb: str = ""

    def putcmd(self, line: str) -> None:
        """Send one command line, then record its verb.

        Args:
            line: The command line without its CRLF.
        """
        super().putcmd(line)
        self.last_verb = line.split(" ", 1)[0].upper()


class FtpClient:
    """FTP access to one SerComm print server per call.

    Args:
        sleep: Waits between refused connects; injected so tests do not wait.
        clock: Monotonic clock that measures the connect deadline.

    Example:
        >>> from sercomm_printserver.application.ports import FtpPort
        >>> port: FtpPort = FtpClient()
        >>> isinstance(port, FtpClient)
        True
    """

    def __init__(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sleep = sleep
        self._clock = clock

    def system_reply(self, endpoint: DeviceEndpoint) -> str:
        """Return the reply to ``SYST`` without logging in.

        Args:
            endpoint: The device to ask.

        Returns:
            The full reply line, for example ``215 Print Server FW 6022``.

        Raises:
            DeviceUnavailableError: The device could not be reached.
            AuthenticationRequiredError: The device answered 530 or 531.
            DeviceResponseError: The reply is not a 215 reply.
        """
        with self._session(endpoint, log_in=False) as ftp:
            reply = ftp.sendcmd("SYST")
        if not reply.startswith("215"):
            raise DeviceResponseError(f"{_where(endpoint)} answered SYST with {_quote(reply, endpoint)}")
        return reply

    def retrieve(self, endpoint: DeviceEndpoint, name: ReadableFile) -> bytes:
        """Download a readable virtual file in binary mode.

        Logs in first only when ``endpoint.login`` is set; this family serves ``CONFIG`` and
        ``PSINF`` without a login.

        Args:
            endpoint: The device to read from.
            name: The file to read.

        Returns:
            The file's exact bytes.

        Raises:
            DeviceUnavailableError: The device could not be reached or dropped the connection.
            AuthenticationRequiredError: The device answered 530 or 531.
            DeviceResponseError: Any other unexpected reply, or a file larger than
                ``MAX_FILE_BYTES``.
        """
        collector = _Collector(endpoint)
        with self._session(endpoint, log_in=True) as ftp:
            ftp.retrbinary(f"RETR {name.value}", collector.add)
        return collector.data()

    def store(self, endpoint: DeviceEndpoint, name: WritableFile, data: bytes) -> None:
        """Upload ``data`` as a writable virtual file in binary mode.

        Per manual, unverified on hardware: log in when configured, ``TYPE I``, then
        ``STOR <name>`` over an active-mode data connection.

        Args:
            endpoint: The device to write to.
            name: The file to write.
            data: The exact bytes to upload.

        Raises:
            DeviceUnavailableError: The device could not be reached or dropped the connection.
            AuthenticationRequiredError: The device answered 530 or 531.
            DeviceResponseError: Any other unexpected reply.
        """
        with self._session(endpoint, log_in=True) as ftp:
            ftp.storbinary(f"STOR {name.value}", io.BytesIO(data))

    def trigger(self, endpoint: DeviceEndpoint, action: DeviceAction) -> None:
        """Trigger an action by ``RETR`` of its file.

        Per manual, unverified on hardware: log in when configured, then ``RETR <action>`` over
        an active-mode data connection. The device may restart (``RESET``, ``DEFAULTC``) and drop
        the control connection instead of completing the transfer, so both a completed transfer
        (any byte count, including none) and a closed or reset control connection AFTER the
        ``RETR`` was sent count as success. A drop before the ``RETR`` went out, a timeout, or
        a 4xx/5xx reply to the ``RETR`` are failures.

        Args:
            endpoint: The device to act on.
            action: The action to trigger.

        Raises:
            DeviceUnavailableError: The device could not be reached, timed out, or dropped the
                connection before the ``RETR`` was sent.
            AuthenticationRequiredError: The device answered 530 or 531.
            DeviceResponseError: Any other unexpected reply.
        """
        collector = _Collector(endpoint)
        with self._session(endpoint, log_in=True) as ftp:
            try:
                ftp.retrbinary(f"RETR {action.value}", collector.add)
            except _CONNECTION_LOST:
                if ftp.last_verb != "RETR":
                    raise
                # The device went down to carry the action out; nothing is left to QUIT.
                ftp.close()

    @contextlib.contextmanager
    def _session(self, endpoint: DeviceEndpoint, *, log_in: bool) -> Generator[_DeviceFTP, None, None]:
        """Open a control connection, optionally log in, and always close it again.

        Args:
            endpoint: The device to talk to.
            log_in: Whether to log in when ``endpoint.login`` is set.

        Yields:
            The connected client in active mode.
        """
        with _translated_errors(endpoint):
            ftp = self._connect(endpoint)
            try:
                if log_in:
                    _log_in(ftp, endpoint)
                yield ftp
            finally:
                _close(ftp)

    def _connect(self, endpoint: DeviceEndpoint) -> _DeviceFTP:
        """Connect, retrying only a refused connect until the deadline.

        Args:
            endpoint: The device to connect to.

        Returns:
            A client that has read the device's 220 banner.

        Raises:
            DeviceUnavailableError: Every connect within the deadline was refused.
        """
        started = self._clock()
        delay = FIRST_BACKOFF_SECONDS
        while True:
            try:
                return _open_control(endpoint)
            except ConnectionRefusedError as exc:
                if self._clock() - started + delay > CONNECT_DEADLINE_SECONDS:
                    raise DeviceUnavailableError(
                        f"{_where(endpoint)} refused the connection for {CONNECT_DEADLINE_SECONDS:g} s"
                    ) from exc
            self._sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)


class _Collector:
    """Gathers a download's blocks and refuses one larger than ``MAX_FILE_BYTES``."""

    def __init__(self, endpoint: DeviceEndpoint) -> None:
        self._endpoint = endpoint
        self._buffer = bytearray()

    def add(self, block: bytes) -> None:
        """Append one received block.

        Args:
            block: Bytes as they arrived on the data connection.

        Raises:
            DeviceResponseError: The file grew past ``MAX_FILE_BYTES``.
        """
        if len(self._buffer) + len(block) > MAX_FILE_BYTES:
            raise DeviceResponseError(f"{_where(self._endpoint)} sent more than {MAX_FILE_BYTES} bytes")
        self._buffer.extend(block)

    def data(self) -> bytes:
        """Return everything received.

        Returns:
            The concatenated blocks.
        """
        return bytes(self._buffer)


def _open_control(endpoint: DeviceEndpoint) -> _DeviceFTP:
    """Open one control connection and read the banner, closing the socket on any failure.

    Args:
        endpoint: The device to connect to.

    Returns:
        A connected client switched to active mode.

    Raises:
        DeviceResponseError: The banner is not a 220 reply.
    """
    # latin-1 decodes any byte, so an odd byte in a reply is quoted instead of raising
    # UnicodeDecodeError out of ftplib's line reader.
    ftp = _DeviceFTP(timeout=endpoint.timeout, encoding="latin-1")
    try:
        banner = ftp.connect(endpoint.host, endpoint.ftp_port, timeout=endpoint.timeout)
        if not banner.startswith("220"):
            raise DeviceResponseError(f"{_where(endpoint)} greeted with {_quote(banner, endpoint)}")
    except BaseException:
        # ftplib keeps a socket whose banner read failed; close it so it does not hold the
        # device's single connection slot.
        ftp.close()
        raise
    ftp.set_pasv(False)
    return ftp


def _log_in(ftp: _DeviceFTP, endpoint: DeviceEndpoint) -> None:
    """Log in with ``USER``/``PASS`` when the endpoint names a login.

    Done by hand rather than with ``ftplib.FTP.login``, which rewrites an empty password for the
    user ``anonymous`` and so could send something the device was never configured with.

    Args:
        ftp: The connected client.
        endpoint: Supplies login and password.

    Raises:
        AuthenticationRequiredError: The device refused the login, or a credential cannot be
            sent on an FTP command line.
        DeviceResponseError: The device answered the login with something other than 2xx/3xx.
    """
    if not endpoint.login:
        return
    password = endpoint.password.get_secret_value()
    _require_sendable(endpoint.login, what="login", endpoint=endpoint)
    _require_sendable(password, what="password", endpoint=endpoint)
    reply = ftp.sendcmd(f"USER {endpoint.login}")
    if reply.startswith("3"):
        reply = ftp.sendcmd(f"PASS {password}")
    if not reply.startswith("2"):
        raise DeviceResponseError(f"{_where(endpoint)} answered the login with {_quote(reply, endpoint)}")


def _require_sendable(text: str, *, what: str, endpoint: DeviceEndpoint) -> None:
    """Refuse a credential that cannot travel on one latin-1 FTP command line.

    Checked up front because ftplib's own refusal (a ValueError or UnicodeEncodeError) would
    carry the whole command line, password included, in its attributes.

    Args:
        text: The login or password.
        what: Its name for the message.
        endpoint: The device, for the message.

    Raises:
        AuthenticationRequiredError: ``text`` holds a line break or a non-latin-1 character.
    """
    if "\r" in text or "\n" in text or any(ord(char) > _LATIN1_MAX for char in text):
        raise AuthenticationRequiredError(
            f"the {what} for {_where(endpoint)} holds a line break or a character FTP cannot send"
        )


def _close(ftp: _DeviceFTP) -> None:
    """End the session with ``QUIT`` when the connection is still open, then close it.

    A failing ``QUIT`` is ignored: the call's work is already done, and the device frees its
    single connection slot when the socket closes either way.

    Args:
        ftp: The client to close.
    """
    if ftp.sock is not None:
        with contextlib.suppress(OSError, EOFError, ftplib.Error):
            ftp.quit()
    ftp.close()


@contextlib.contextmanager
def _translated_errors(endpoint: DeviceEndpoint) -> Generator[None, None, None]:
    """Turn socket and ftplib failures into the domain's device errors.

    Args:
        endpoint: The device, named in every message.

    Yields:
        Nothing; the body runs with translation in place.

    Raises:
        AuthenticationRequiredError: For a 530 or 531 reply.
        DeviceResponseError: For any other error reply or protocol violation.
        DeviceUnavailableError: For a timeout, a lost connection or any other socket failure.
    """
    where = _where(endpoint)
    try:
        yield
    except (DeviceUnavailableError, AuthenticationRequiredError):
        raise
    except ftplib.Error as exc:
        raise _reply_error(exc, endpoint) from _safe_cause(exc, endpoint)
    except EOFError as exc:
        raise DeviceUnavailableError(f"{where} closed the connection") from exc
    except TimeoutError as exc:
        raise DeviceUnavailableError(f"{where} did not answer within {endpoint.timeout:g} s") from exc
    except OSError as exc:
        raise DeviceUnavailableError(f"{where} is unreachable: {exc.strerror or type(exc).__name__}") from exc


def _reply_error(exc: ftplib.Error, endpoint: DeviceEndpoint) -> Exception:
    """Map an ftplib reply error to the matching domain error.

    Args:
        exc: The ftplib error; its text is the device's reply.
        endpoint: The device, for the message and for redaction.

    Returns:
        ``AuthenticationRequiredError`` for 530 (not logged in) and 531 (the PS301's "Invalid
        password."), otherwise ``DeviceResponseError``.
    """
    reply = str(exc)
    if reply.startswith(("530", "531")):
        return AuthenticationRequiredError(f"{_where(endpoint)} refused the login: {_quote(reply, endpoint)}")
    return DeviceResponseError(f"{_where(endpoint)} answered {_quote(reply, endpoint)}")


def _safe_cause(exc: BaseException, endpoint: DeviceEndpoint) -> BaseException | None:
    """Return ``exc`` as the cause unless its text carries the password.

    A device that echoes the received password in its refusal would otherwise put it into
    the printed traceback through the chained cause.

    Args:
        exc: The original exception.
        endpoint: Supplies the password to look for.

    Returns:
        ``exc``, or None when chaining it would show the password.
    """
    password = endpoint.password.get_secret_value()
    if password and password in str(exc):
        return None
    return exc


def _quote(reply: str, endpoint: DeviceEndpoint) -> str:
    """Quote a reply for a message: password masked, length bounded.

    Args:
        reply: The device's reply text.
        endpoint: Supplies the password to mask.

    Returns:
        The ``repr`` of the masked, truncated reply.
    """
    password = endpoint.password.get_secret_value()
    text = reply.replace(password, "***") if password else reply
    if len(text) > _REPLY_QUOTE_LIMIT:
        text = text[:_REPLY_QUOTE_LIMIT] + "..."
    return repr(text)


def _where(endpoint: DeviceEndpoint) -> str:
    """Return ``host:port`` of the endpoint's FTP service.

    Args:
        endpoint: The device.

    Returns:
        The address as used in messages.
    """
    return f"{endpoint.host}:{endpoint.ftp_port}"


__all__ = [
    "CONNECT_DEADLINE_SECONDS",
    "FIRST_BACKOFF_SECONDS",
    "MAX_BACKOFF_SECONDS",
    "MAX_FILE_BYTES",
    "FtpClient",
]
