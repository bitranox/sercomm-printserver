"""Strip Telnet IAC command sequences out of a received byte stream.

The print server opens every Telnet session with ``IAC WILL ECHO, IAC DO SGA, IAC WILL SGA``
and works whether or not the client answers, so the client never negotiates: it only has to
remove the command bytes before it looks for the ``PS>`` prompt and before the monitor text
reaches the parser. A sequence can be split across two ``recv`` calls, which is why the
stripper keeps its position between chunks instead of working on one chunk at a time.

Sequences removed (RFC 854/855):

* ``IAC WILL|WONT|DO|DONT <option>``: three bytes, dropped;
* ``IAC SB ... IAC SE``: a subnegotiation, dropped whole;
* ``IAC IAC``: an escaped data byte, kept as one ``0xFF``;
* ``IAC <other>`` (NOP, GA, ...): two bytes, dropped.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

IAC: Final = 0xFF
SB: Final = 0xFA
SE: Final = 0xF0
_NEGOTIATION: Final = frozenset({0xFB, 0xFC, 0xFD, 0xFE})  # WILL, WONT, DO, DONT


class _State(Enum):
    """Where the stripper stands inside the byte stream."""

    DATA = "data"
    COMMAND = "command"
    OPTION = "option"
    SUBNEGOTIATION = "subnegotiation"
    SUBNEGOTIATION_IAC = "subnegotiation-iac"


def _in_data(byte: int, out: bytearray) -> _State:
    if byte == IAC:
        return _State.COMMAND
    out.append(byte)
    return _State.DATA


def _in_command(byte: int, out: bytearray) -> _State:
    if byte == IAC:
        out.append(IAC)
        return _State.DATA
    if byte == SB:
        return _State.SUBNEGOTIATION
    if byte in _NEGOTIATION:
        return _State.OPTION
    return _State.DATA


def _in_option(_byte: int, _out: bytearray) -> _State:
    return _State.DATA


def _in_subnegotiation(byte: int, _out: bytearray) -> _State:
    return _State.SUBNEGOTIATION_IAC if byte == IAC else _State.SUBNEGOTIATION


def _in_subnegotiation_iac(byte: int, _out: bytearray) -> _State:
    # IAC IAC inside a subnegotiation is an escaped data byte of the subnegotiation: still dropped.
    return _State.DATA if byte == SE else _State.SUBNEGOTIATION


_HANDLERS: Final[dict[_State, Callable[[int, bytearray], _State]]] = {
    _State.DATA: _in_data,
    _State.COMMAND: _in_command,
    _State.OPTION: _in_option,
    _State.SUBNEGOTIATION: _in_subnegotiation,
    _State.SUBNEGOTIATION_IAC: _in_subnegotiation_iac,
}


class IacStripper:
    """Remove Telnet command sequences from consecutive chunks of one stream.

    Example:
        >>> stripper = IacStripper()
        >>> stripper.feed(b"\\xff\\xfb\\x01Welcome\\xff")
        b'Welcome'
        >>> stripper.feed(b"\\xff to PS>")
        b'\\xff to PS>'
    """

    def __init__(self) -> None:
        """Start at the beginning of a stream, outside any command."""
        self._state = _State.DATA

    def feed(self, chunk: bytes) -> bytes:
        """Return the data bytes of ``chunk``, remembering an unfinished sequence for the next.

        Args:
            chunk: The next bytes received on the connection.

        Returns:
            The bytes that are data, with every command sequence removed and ``IAC IAC``
            turned into one ``0xFF``.
        """
        if self._state is _State.DATA and IAC not in chunk:
            return chunk
        out = bytearray()
        for byte in chunk:
            self._state = _HANDLERS[self._state](byte, out)
        return bytes(out)


__all__ = ["IAC", "SB", "SE", "IacStripper"]
