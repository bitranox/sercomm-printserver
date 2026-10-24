"""Port status from the Telnet ``monitor`` command.

One block per physical port, separated by blank lines::

    (P1)STATE: Printing
    TYPE: Parallel
    PRINTER STATUS: Offline
    BYTES SERVICED:          0
    OCCUPIED BY: Direct Socket

An idle port prints only the first three lines. The port name and the values of STATE, TYPE and
PRINTER STATUS come from fixed tables in the firmware, so they are closed enums here and an
unknown one is refused rather than guessed at; OCCUPIED BY names whatever protocol holds the port
and stays text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Final, NamedTuple

from pydantic import BaseModel, BeforeValidator, Field, ValidationError

from .config_types import PortId
from .errors import DeviceResponseError

if TYPE_CHECKING:
    from pydantic_core import ErrorDetails

_BLOCK_START: Final = re.compile(r"\((?P<port>[A-Z0-9]{1,4})\)STATE:\s*(?P<state>.*)")
_STATE_KEY: Final = "STATE"
_BYTES_KEY: Final = "BYTES SERVICED"
_PORT_FIELD: Final = "port"


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


def _ascii_digits(value: object) -> object:
    # int() would also take "+5", " 5", "1_000" and non-ASCII digits; the firmware prints none of
    # those, so a wire string must be plain ASCII digits before it becomes a count.
    if isinstance(value, str) and not (value.isascii() and value.isdigit()):
        raise ValueError("expected a number")
    return value


class PortStatus(BaseModel, frozen=True, extra="forbid", validate_by_name=True, validate_by_alias=True):
    """Status of one physical port.

    The validation aliases are the ``monitor`` line names, so a block validates straight into this
    model; construction by field name works as well.

    Example:
        >>> ports = parse_monitor("(P1)STATE: Idle\\r\\nTYPE: Parallel\\r\\nPRINTER STATUS: Offline\\r\\n")
        >>> ports[0].port.value, ports[0].state.value, ports[0].bytes_serviced
        ('P1', 'Idle', None)
        >>> fields = {"port": "SP", "state": "Idle", "type": "Serial", "printer_status": "On-Line"}
        >>> PortStatus.model_validate(fields).port is PortId.SP
        True
    """

    port: PortId
    state: PortState = Field(validation_alias=_STATE_KEY)
    type: PortType = Field(validation_alias="TYPE")
    printer_status: PrinterStatus = Field(validation_alias="PRINTER STATUS")
    bytes_serviced: Annotated[int | None, BeforeValidator(_ascii_digits)] = Field(
        default=None, ge=0, validation_alias=_BYTES_KEY
    )
    occupied_by: str | None = Field(default=None, validation_alias="OCCUPIED BY")


def _wire_keys() -> frozenset[str]:
    aliases = (field.validation_alias for field in PortStatus.model_fields.values())
    return frozenset(alias for alias in aliases if isinstance(alias, str))


_WIRE_KEYS: Final = _wire_keys()
# The order the parser has always reported a block's defects in: the byte count first, then the
# enum lines top to bottom. The port name goes last, so a block that has another defect too keeps
# reporting that one.
_PRECEDENCE: Final = (_BYTES_KEY, _STATE_KEY, "TYPE", "PRINTER STATUS", _PORT_FIELD)


class _MonitorLine(NamedTuple):
    key: str
    value: str


@dataclass
class _Block:
    port: str
    lines: list[_MonitorLine]


def parse_monitor(text: str) -> tuple[PortStatus, ...]:
    """Parse the output of ``monitor``; text before the first port block is ignored.

    Raises:
        DeviceResponseError: No port block was found, a block lacks a line, or a port name or
            value is not one the firmware prints.
    """
    blocks = _blocks(text)
    if not blocks:
        raise DeviceResponseError("monitor output holds no port status")
    return tuple(_status(block) for block in blocks)


def _blocks(text: str) -> list[_Block]:
    blocks: list[_Block] = []
    current: _Block | None = None
    for raw in text.splitlines():
        line = raw.strip()
        start = _BLOCK_START.fullmatch(line)
        if start is not None:
            current = _Block(port=start["port"], lines=[_MonitorLine(_STATE_KEY, start["state"].strip())])
            blocks.append(current)
        elif not line:
            current = None
        elif current is not None:
            key, _, value = line.partition(":")
            current.lines.append(_MonitorLine(key.strip(), value.strip()))
    return blocks


def _status(block: _Block) -> PortStatus:
    wire = {line.key: line.value for line in block.lines}
    unknown = sorted(wire.keys() - _WIRE_KEYS)
    if unknown:
        raise DeviceResponseError(f"port {block.port}: unexpected monitor line(s) {', '.join(unknown)}")
    try:
        return PortStatus.model_validate({**wire, _PORT_FIELD: block.port}, by_alias=True, by_name=False)
    except ValidationError as error:
        raise _refusal(block.port, error) from None


def _refusal(port: str, error: ValidationError) -> DeviceResponseError:
    first = min(error.errors(), key=_precedence)
    key = str(first["loc"][0])
    if first["type"] == "missing":
        return DeviceResponseError(f"port {port}: monitor output has no {key} line")
    if key == _BYTES_KEY:
        return DeviceResponseError(f"port {port}: {key} is {first['input']!r}, expected a number")
    if key == _PORT_FIELD:
        return DeviceResponseError(f"port {port}: port name is {port!r}, which this firmware family does not print")
    return DeviceResponseError(f"port {port}: {key} is {first['input']!r}, which this firmware family does not print")


def _precedence(detail: ErrorDetails) -> int:
    return _PRECEDENCE.index(str(detail["loc"][0]))


__all__ = ["PortState", "PortStatus", "PortType", "PrinterStatus", "parse_monitor"]
