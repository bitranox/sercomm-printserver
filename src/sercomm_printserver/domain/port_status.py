"""Port status from the Telnet ``monitor`` command.

One block per physical port, separated by blank lines::

    (P1)STATE: Printing
    TYPE: Parallel
    PRINTER STATUS: Offline
    BYTES SERVICED:          0
    OCCUPIED BY: Direct Socket

An idle port prints only the first three lines. The values of STATE, TYPE and PRINTER STATUS
come from a fixed table in the firmware, so they are closed enums here and an unknown one is
refused rather than guessed at; OCCUPIED BY names whatever protocol holds the port and stays
text.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Final, TypeVar

from pydantic import BaseModel, Field

from .errors import DeviceResponseError

_BLOCK_START: Final = re.compile(r"\((?P<port>[A-Z0-9]{1,4})\)STATE:\s*(?P<state>.*)")
_E = TypeVar("_E", bound=Enum)


class PortState(str, Enum):
    """Whether the port is printing a job."""

    IDLE = "Idle"
    PRINTING = "Printing"


class PortType(str, Enum):
    """Kind of physical port."""

    PARALLEL = "Parallel"
    SERIAL = "Serial"
    USB = "USB"


class PrinterStatus(str, Enum):
    """What the printer on the port reports."""

    ON_LINE = "On-Line"
    OFFLINE = "Offline"
    OUT_OF_PAPER = "Out Of Paper"


class PortStatus(BaseModel, frozen=True, extra="forbid"):
    """Status of one physical port.

    Example:
        >>> ports = parse_monitor("(P1)STATE: Idle\\r\\nTYPE: Parallel\\r\\nPRINTER STATUS: Offline\\r\\n")
        >>> ports[0].port, ports[0].state.value, ports[0].bytes_serviced
        ('P1', 'Idle', None)
    """

    port: str
    state: PortState
    type: PortType
    printer_status: PrinterStatus
    bytes_serviced: int | None = Field(default=None, ge=0)
    occupied_by: str | None = None


def parse_monitor(text: str) -> tuple[PortStatus, ...]:
    """Parse the output of ``monitor``; text before the first port block is ignored.

    Raises:
        DeviceResponseError: No port block was found, a block lacks a line, or a value is not one
            the firmware prints.
    """
    blocks = _blocks(text)
    if not blocks:
        raise DeviceResponseError("monitor output holds no port status")
    return tuple(_status(port, fields) for port, fields in blocks)


def _blocks(text: str) -> list[tuple[str, dict[str, str]]]:
    blocks: list[tuple[str, dict[str, str]]] = []
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        start = _BLOCK_START.fullmatch(line)
        if start is not None:
            current = {"STATE": start["state"].strip()}
            blocks.append((start["port"], current))
        elif not line:
            current = None
        elif current is not None:
            key, _, value = line.partition(":")
            current[key.strip()] = value.strip()
    return blocks


def _status(port: str, fields: dict[str, str]) -> PortStatus:
    known = {"STATE", "TYPE", "PRINTER STATUS", "BYTES SERVICED", "OCCUPIED BY"}
    unknown = sorted(fields.keys() - known)
    if unknown:
        raise DeviceResponseError(f"port {port}: unexpected monitor line(s) {', '.join(unknown)}")
    bytes_serviced = fields.get("BYTES SERVICED")
    if bytes_serviced is not None and not (bytes_serviced.isascii() and bytes_serviced.isdigit()):
        raise DeviceResponseError(f"port {port}: BYTES SERVICED is {bytes_serviced!r}, expected a number")
    return PortStatus(
        port=port,
        state=_member(port, "STATE", fields, PortState),
        type=_member(port, "TYPE", fields, PortType),
        printer_status=_member(port, "PRINTER STATUS", fields, PrinterStatus),
        bytes_serviced=None if bytes_serviced is None else int(bytes_serviced),
        occupied_by=fields.get("OCCUPIED BY"),
    )


def _member(port: str, key: str, fields: dict[str, str], enum_type: type[_E]) -> _E:
    if key not in fields:
        raise DeviceResponseError(f"port {port}: monitor output has no {key} line")
    for member in enum_type:
        if member.value == fields[key]:
            return member
    raise DeviceResponseError(f"port {port}: {key} is {fields[key]!r}, which this firmware family does not print")


__all__ = ["PortState", "PortStatus", "PortType", "PrinterStatus", "parse_monitor"]
