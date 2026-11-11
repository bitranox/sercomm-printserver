"""How long a print server needs to pass a RAW job on to its printer.

A PS301 takes a whole RAW job at once and passes it on at the speed of the link its printer
hangs on. A NEW RAW connection opened before it has finished loses its data, and the port is left
reading ``Printing`` / ``Direct Socket`` with 0 bytes serviced until the device restarts
(measured 2026-11-10 on FW 6022 with a serial printer at 9600 8N1: a 1361-byte job then a new
connection 0.5 s later wedged it 3 of 3 times, 3 s later 0 of 3). Keeping the job's connection
open for the job's bytes at the link rate, plus a margin, prevented it in every measured round.

Only the serial port is slow enough to matter: its rate follows from the configured frame. That
a parallel or USB printer needs no wait is not measured (the test device has no printer there).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, Field

from .config_types import Parity, PortId
from .errors import DeviceResponseError

if TYPE_CHECKING:
    from .config_model import DeviceConfig, SerialPort

#: Seconds added to the drain time. Measured on a PS301 at 9600 8N1: margins of 0.25, 0.5 and 1.0 s
#: kept a query sent at once after a 1361- or 4753-byte job answered, closing at once wedged the
#: port every time; below 0.25 s is unmeasured.
DRAIN_MARGIN_SECONDS: Final = 0.25
#: The start bit every serial frame begins with.
_START_BITS: Final = 1


class LinkDrain(BaseModel, frozen=True, extra="forbid"):
    """The link a job has to cross after the print server took it.

    Example:
        >>> LinkDrain(bytes_per_second=960.0).seconds_for(960)
        1.25
    """

    bytes_per_second: float = Field(gt=0)
    margin: float = Field(default=DRAIN_MARGIN_SECONDS, ge=0)

    def seconds_for(self, size: int) -> float:
        """Seconds ``size`` bytes need to cross the link, margin included."""
        return size / self.bytes_per_second + self.margin


def serial_link(serial: SerialPort) -> LinkDrain:
    """The link of a serial port: its baud rate over the bits of one frame.

    Example:
        >>> from sercomm_printserver.domain.config_model import SerialPort
        >>> from sercomm_printserver.domain.config_types import BaudRate, DataBits, Handshake, StopBits
        >>> port = SerialPort(
        ...     baud_rate=BaudRate.B9600, stop_bits=StopBits.ONE, parity=Parity.NONE,
        ...     data_bits=DataBits.EIGHT, handshake=Handshake.BOTH,
        ... )
        >>> serial_link(port).bytes_per_second
        960.0
    """
    parity_bits = 0 if serial.parity is Parity.NONE else 1
    frame = _START_BITS + int(serial.data_bits) + parity_bits + int(serial.stop_bits)
    return LinkDrain(bytes_per_second=int(serial.baud_rate) / frame)


def link_drain_for(config: DeviceConfig, port: PortId) -> LinkDrain | None:
    """The link a job routed to ``port`` crosses, or None when it needs no wait.

    Raises:
        DeviceResponseError: ``port`` is the serial port but the configuration has no serial
            settings, so its speed is unknown.
    """
    if port is not PortId.SP:
        return None
    if config.serial is None:
        raise DeviceResponseError("the configuration routes a printer to SP but has no serial port settings")
    return serial_link(config.serial)


__all__ = ["DRAIN_MARGIN_SECONDS", "LinkDrain", "link_drain_for", "serial_link"]
