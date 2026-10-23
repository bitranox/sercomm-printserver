"""Telnet console client for the print server's ``monitor`` command.

Device dialect (measured on a PS301, firmware 6022):

* No login. On connect the device sends ``IAC WILL ECHO, IAC DO SGA, IAC WILL SGA``, a
  ``Welcome to Print Server`` banner and the prompt ``PS>``. It works without any answer to
  the negotiation, so the client sends none and strips the command bytes instead.
* ``monitor`` prints one block per port but no new prompt afterwards, so the client cannot wait
  for a second prompt. It sends ``monitor`` and ``exit`` in one write and reads until the device
  closes the connection; that close is the only end-of-output signal the device gives.
* The device echoes the command lines; they are removed from the returned text.

Every ``recv`` is bounded by ``endpoint.timeout`` and the whole response by a byte cap, so a
peer that never closes or never stops sending cannot hold the caller or its memory.
"""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Final

from ...domain.errors import DeviceResponseError, DeviceUnavailableError
from .iac import IacStripper

if TYPE_CHECKING:
    from ...domain.endpoint import DeviceEndpoint

PROMPT: Final = b"PS>"
MONITOR_COMMAND: Final = b"monitor\r\nexit\r\n"
DEFAULT_MAX_RESPONSE_BYTES: Final = 64 * 1024
_RECV_SIZE: Final = 4096
_EXCERPT_BYTES: Final = 80


def _excerpt(data: bytes | bytearray) -> str:
    """Quote received bytes for an error message, cut so a long stream stays readable."""
    head = repr(bytes(data[:_EXCERPT_BYTES]))
    return head + "..." if len(data) > _EXCERPT_BYTES else head


def _connect(host: str, port: int, timeout: float) -> socket.socket:
    """Open the TCP connection, mapping every failure to ``DeviceUnavailableError``."""
    try:
        return socket.create_connection((host, port), timeout=timeout)
    except (OSError, UnicodeError) as exc:
        # UnicodeError: the IDNA codec refuses a malformed host name before any socket exists.
        raise DeviceUnavailableError(f"{host}:{port} could not be reached: {exc}") from exc


class _SessionReader:
    """Read one Telnet session, stripping IAC sequences and enforcing the byte cap."""

    def __init__(self, sock: socket.socket, *, address: str, limit: int) -> None:
        self._sock = sock
        self._address = address
        self._limit = limit
        self._received = 0
        self._stripper = IacStripper()

    def chunk(self) -> bytes | None:
        """Return the next data bytes, or None at end of stream.

        Raises:
            TimeoutError: The device sent nothing within the socket timeout; the caller knows
                which phase it was in and words the error.
            DeviceUnavailableError: The connection broke (reset, aborted).
            DeviceResponseError: The device sent more than the byte cap.
        """
        try:
            raw = self._sock.recv(_RECV_SIZE)
        except TimeoutError:
            raise
        except OSError as exc:
            raise DeviceUnavailableError(f"{self._address} broke the connection: {exc}") from exc
        if not raw:
            return None
        self._received += len(raw)
        if self._received > self._limit:
            raise DeviceResponseError(f"{self._address} sent more than {self._limit} bytes; stopped reading")
        return self._stripper.feed(raw)

    def until_prompt(self, timeout: float) -> bytes:
        """Read up to the ``PS>`` prompt and return whatever followed it in the same reads.

        Raises:
            DeviceResponseError: No prompt arrived before the timeout or the end of stream.
        """
        seen = bytearray()
        while (position := seen.find(PROMPT)) < 0:
            try:
                data = self.chunk()
            except TimeoutError as exc:
                raise DeviceResponseError(
                    f"{self._address} sent no PS> prompt within {timeout} s; received {_excerpt(seen)}"
                ) from exc
            if data is None:
                raise DeviceResponseError(f"{self._address} closed before the PS> prompt; received {_excerpt(seen)}")
            seen += data
        return bytes(seen[position + len(PROMPT) :])

    def until_end(self, timeout: float) -> bytes:
        """Read until the device closes the connection.

        Raises:
            DeviceResponseError: The device answered but did not close within the timeout, so
                the output may be incomplete.
        """
        seen = bytearray()
        while True:
            try:
                data = self.chunk()
            except TimeoutError as exc:
                raise DeviceResponseError(
                    f"{self._address} did not finish the monitor output within {timeout} s; received {_excerpt(seen)}"
                ) from exc
            if data is None:
                return bytes(seen)
            seen += data


class TelnetClient:
    """``TelnetPort`` over a plain TCP socket, one connection per call.

    Example:
        >>> from sercomm_printserver.application.ports import TelnetPort
        >>> port: TelnetPort = TelnetClient()
        >>> TelnetClient(max_response_bytes=0)
        Traceback (most recent call last):
        ...
        ValueError: max_response_bytes must be positive, got 0
    """

    def __init__(self, *, max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES) -> None:
        """Configure the client.

        Args:
            max_response_bytes: The most bytes one session may deliver before the client gives
                up with ``DeviceResponseError``; the real monitor output is under 300 bytes.

        Raises:
            ValueError: ``max_response_bytes`` is not positive.
        """
        if max_response_bytes < 1:
            raise ValueError(f"max_response_bytes must be positive, got {max_response_bytes}")
        self._max_response_bytes = max_response_bytes

    def monitor(self, endpoint: DeviceEndpoint) -> str:
        """Return the text the ``monitor`` command prints.

        Args:
            endpoint: The device; ``host``, ``telnet_port`` and ``timeout`` are used.

        Returns:
            The output after the echoed command lines, decoded as ASCII (an undecodable byte
            becomes U+FFFD). It starts with the blank line before the first port block.

        Raises:
            DeviceUnavailableError: The device could not be reached or broke the connection.
            DeviceResponseError: No ``PS>`` prompt, no end of output within the timeout, or
                more output than the byte cap.
        """
        address = f"{endpoint.host}:{endpoint.telnet_port}"
        with _connect(endpoint.host, endpoint.telnet_port, endpoint.timeout) as sock:
            reader = _SessionReader(sock, address=address, limit=self._max_response_bytes)
            after_prompt = reader.until_prompt(endpoint.timeout)
            _send(sock, MONITOR_COMMAND, address=address)
            output = after_prompt + reader.until_end(endpoint.timeout)
        return output.removeprefix(MONITOR_COMMAND).decode("ascii", errors="replace")


def _send(sock: socket.socket, data: bytes, *, address: str) -> None:
    """Send the command lines, mapping a broken connection to ``DeviceUnavailableError``."""
    try:
        sock.sendall(data)
    except OSError as exc:
        raise DeviceUnavailableError(f"{address} broke the connection while the command was sent: {exc}") from exc


__all__ = ["DEFAULT_MAX_RESPONSE_BYTES", "MONITOR_COMMAND", "PROMPT", "TelnetClient"]
