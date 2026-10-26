"""Value types of the print server's CONFIG parameters.

The enums carry the exact spelling the firmware prints, so rendering a configuration is
``member.value`` and nothing else. The value sets come from the firmware's own value-string
table and the vendor manuals; ``docs/config-keys.md`` lists the source per parameter.

The package supports Python 3.10, so the string enums are ``str, Enum`` rather than
``StrEnum``: interpolating a member formats differently on 3.10 and 3.11+, which is why
every renderer reads ``.value``.
"""

from __future__ import annotations

import re
from enum import Enum, IntEnum
from typing import Annotated, Final

from pydantic import AfterValidator, Field

#: Characters the device's line format can carry in a value: printable ASCII. A newline would
#: end the line and start a new parameter, so it is refused rather than escaped.
_PRINTABLE: Final = re.compile(r"[\x20-\x7e]*")
_NO_SPACES: Final = re.compile(r"[\x21-\x7e]+")
_HEX_PAIRS: Final = re.compile(r"(?:[0-9A-Fa-f]{2})*")


def _text_rule(max_length: int) -> AfterValidator:
    def check(value: str) -> str:
        if len(value) > max_length or not _PRINTABLE.fullmatch(value):
            raise ValueError(f"must be at most {max_length} printable ASCII characters")
        return value

    return AfterValidator(check)


def _check_box_name(value: str) -> str:
    # Empty is the factory state (measured, FW 6022), so a reset device's CONFIG must parse.
    if len(value) > _BOX_NAME_MAX or (value and not _NO_SPACES.fullmatch(value)):
        raise ValueError(f"must be at most {_BOX_NAME_MAX} printable ASCII characters without spaces")
    return value


def _check_hex(value: str) -> str:
    if len(value) > _HEX_MAX_DIGITS or not _HEX_PAIRS.fullmatch(value):
        raise ValueError("must be pairs of hex digits, at most 15 bytes (<Esc>3 is written 1B33)")
    return value


_BOX_NAME_MAX: Final = 19
_HEX_MAX_DIGITS: Final = 30

Text7 = Annotated[str, _text_rule(7)]
Text15 = Annotated[str, _text_rule(15)]
Text19 = Annotated[str, _text_rule(19)]
Text31 = Annotated[str, _text_rule(31)]
Text39 = Annotated[str, _text_rule(39)]
Text47 = Annotated[str, _text_rule(47)]
Text235 = Annotated[str, _text_rule(235)]

#: Device name: the manuals allow letters and digits, no spaces, at most 19 characters.
#: The FTP login and the default AppleTalk names derive from it. Empty after a factory reset.
BoxName = Annotated[str, AfterValidator(_check_box_name)]

#: Control string sent before or after a job, written as hex digits (``<Esc>3`` is ``1B33``),
#: at most 15 bytes.
HexString = Annotated[str, AfterValidator(_check_hex)]

Byte = Annotated[int, Field(ge=0, le=255)]
Word = Annotated[int, Field(ge=0, le=65535)]
Severity = Annotated[int, Field(ge=0, le=2)]
Slot = Annotated[int, Field(ge=1, le=9)]


class PortId(str, Enum):
    """Physical port a logical printer prints to.

    Example:
        >>> PortId("SP").value
        'SP'
    """

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    SP = "SP"


class LptMode(str, Enum):
    """Handshake signal the print server checks on a parallel port."""

    BUSY = "Busy"
    ACK_AND_BUSY = "Ack&Busy"


class NetWareMode(str, Enum):
    """NetWare operation: queue-servicing print server or remote printer."""

    PRINT_SERVER = "PS"
    REMOTE_PRINTER = "RP"


class BaudRate(IntEnum):
    """Serial port speed."""

    B300 = 300
    B600 = 600
    B1200 = 1200
    B2400 = 2400
    B4800 = 4800
    B9600 = 9600
    B19200 = 19200
    B38400 = 38400


class StopBits(IntEnum):
    """Serial port stop bits."""

    ONE = 1
    TWO = 2


class DataBits(IntEnum):
    """Serial port data bits."""

    SEVEN = 7
    EIGHT = 8


class Parity(str, Enum):
    """Serial port parity, spelled as the firmware prints it."""

    NONE = "None"
    ODD = "ODD"
    EVEN = "EVEN"


class Handshake(str, Enum):
    """Serial port flow control, spelled as the firmware prints it."""

    NONE = "None"
    XON_XOFF = "XON/XOFF"
    HARDWARE = "HARDWARE"
    BOTH = "BOTH"


class AccessRight(str, Enum):
    """What an SNMP management station may do."""

    READ_ONLY = "Read Only"
    READ_WRITE = "Read/Write"
    NOT_ACCESSIBLE = "Not Accessible"


__all__ = [
    "AccessRight",
    "BaudRate",
    "BoxName",
    "Byte",
    "DataBits",
    "Handshake",
    "HexString",
    "LptMode",
    "NetWareMode",
    "Parity",
    "PortId",
    "Severity",
    "Slot",
    "StopBits",
    "Text7",
    "Text15",
    "Text19",
    "Text31",
    "Text39",
    "Text47",
    "Text235",
    "Word",
]
