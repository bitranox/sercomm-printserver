"""The RAW ports of the logical printers L1 to L3: two rows, and which firmware opens which.

A RAW port belongs to a logical printer, not to a physical port: its data goes wherever that
printer is routed (``Ln_PROUT``), as an LPD job would. The firmware fixes the port numbers; no
CONFIG key sets them, in none of ten vendor firmware images. There are two rows:

- ``BASE``: ``raw_port_base`` + 0/1/2, 9100-9102 by default (the JetDirect convention).
- ``DSI``: the vendor's direct socket ports 4010, 4020 and 4030, which every vendor manual names.

Which rows a device opens depends on its firmware (``raw_port_rows``): a PS301 with firmware 6022
opens both (measured 2026-10-24), one with firmware 6A10 only the DSI row (measured 2026-11-27:
9100-9102 refused every connect for over 8 minutes after a restart, 4010-4030 accepted). Any other
firmware is unmeasured, so its rows are unknown.

Example:
    >>> raw_port_of(3, RawPortRow.DSI, raw_port_base=9100), raw_port_of(3, RawPortRow.BASE, raw_port_base=9100)
    (4030, 9102)
    >>> sorted(row.value for row in raw_port_rows("6A10"))
    ['dsi']
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final

#: The logical printers that have a RAW port: L1 to L3.
RAW_PRINTERS: Final = (1, 2, 3)

#: The DSI row: the RAW ports of L1, L2 and L3.
DSI_RAW_PORTS: Final = (4010, 4020, 4030)

#: The highest TCP port.
_LAST_PORT: Final = 65535


class RawPortRow(str, Enum):
    """Which row of RAW ports a job is sent to.

    ``str, Enum`` rather than ``StrEnum``, which Python 3.10 lacks; read ``.value`` for the text.
    """

    #: ``raw_port_base`` + 0/1/2 (9100-9102 by default).
    BASE = "base"
    #: 4010, 4020 and 4030.
    DSI = "dsi"


@dataclass(frozen=True, slots=True)
class RawPrinter:
    """The logical printer a RAW port belongs to, and the row the port is in.

    Attributes:
        logical_printer: 1 to 3.
        row: The row the port is in.
    """

    logical_printer: int
    row: RawPortRow


#: The rows each measured firmware opens; the key is the version as the device prints it, upper case.
_ROWS_BY_FIRMWARE: Final = MappingProxyType(
    {
        "6022": frozenset({RawPortRow.BASE, RawPortRow.DSI}),
        "6A10": frozenset({RawPortRow.DSI}),
    }
)


def raw_port_of(logical_printer: int, row: RawPortRow, *, raw_port_base: int) -> int:
    """The RAW port of ``logical_printer`` in ``row``.

    Args:
        logical_printer: 1 to 3.
        row: The row of ports.
        raw_port_base: The BASE row's port of L1; the DSI row does not use it.

    Raises:
        ValueError: The printer has no RAW port in that row (only L1..L3 have one, and the BASE
            row cannot pass port 65535).

    Example:
        >>> raw_port_of(2, RawPortRow.BASE, raw_port_base=9100)
        9101
    """
    if logical_printer not in RAW_PRINTERS:
        raise ValueError(f"logical printer {logical_printer} has no RAW port: only L1..L3 have one")
    if row is RawPortRow.DSI:
        return DSI_RAW_PORTS[logical_printer - 1]
    port = raw_port_base + logical_printer - 1
    if port > _LAST_PORT:
        raise ValueError(f"logical printer {logical_printer} has no RAW port: {port} is past port {_LAST_PORT}")
    return port


def raw_printer_at(port: int, *, raw_port_base: int) -> RawPrinter | None:
    """The logical printer whose RAW port ``port`` is, in either row; None when it is in neither.

    A BASE row that overlaps the DSI row (a ``raw_port_base`` of 4008 to 4030) is read first.

    Example:
        >>> raw_printer_at(4020, raw_port_base=9100)
        RawPrinter(logical_printer=2, row=<RawPortRow.DSI: 'dsi'>)
        >>> raw_printer_at(515, raw_port_base=9100) is None
        True
    """
    for row in RawPortRow:
        for number in RAW_PRINTERS:
            if port == _port_or_none(number, row, raw_port_base):
                return RawPrinter(logical_printer=number, row=row)
    return None


def _port_or_none(number: int, row: RawPortRow, raw_port_base: int) -> int | None:
    try:
        return raw_port_of(number, row, raw_port_base=raw_port_base)
    except ValueError:
        return None


def raw_port_rows(firmware_version: str) -> frozenset[RawPortRow] | None:
    """The rows of RAW ports a device with ``firmware_version`` opens; None for an unmeasured firmware.

    Examples:
        >>> sorted(row.value for row in raw_port_rows("6022"))
        ['base', 'dsi']
        >>> raw_port_rows("6034") is None
        True
    """
    return _ROWS_BY_FIRMWARE.get(firmware_version.strip().upper())


__all__ = [
    "DSI_RAW_PORTS",
    "RAW_PRINTERS",
    "RawPortRow",
    "RawPrinter",
    "raw_port_of",
    "raw_port_rows",
    "raw_printer_at",
]
