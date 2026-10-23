"""Read CONFIG lines into a :class:`~.config_model.DeviceConfig`.

Every parameter is read by its line number through :class:`_Reader`, which remembers what it
consumed; whatever is left over becomes :attr:`DeviceConfig.unmodeled`, so nothing the device
reported is lost. A group is present exactly when its first line is: a 1-port model simply has
fewer logical printers, no serial port, and so on.

Spellings are matched without regard to case (the manuals print ``yes`` where the firmware
prints ``Yes``); the renderer always writes the firmware's spelling.
"""

from __future__ import annotations

from enum import Enum, IntEnum
from ipaddress import AddressValueError, IPv4Address
from typing import TYPE_CHECKING, TypeVar

from pydantic import ValidationError

from . import config_catalogue as cat
from .config_model import (
    AppleTalk,
    DeviceConfig,
    LogicalPrinter,
    Mail,
    NetWare,
    ParallelMode,
    Protocols,
    SerialPort,
    SlotFlag,
    SlotText,
    Smb,
    Snmp,
    SnmpManager,
    SnmpTrap,
    TcpIp,
)
from .config_types import AccessRight, BaudRate, DataBits, Handshake, LptMode, NetWareMode, Parity, PortId, StopBits
from .errors import ConfigFormatError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pydantic_core import ErrorDetails

    from .config_lines import ConfigLine

_E = TypeVar("_E", bound=Enum)
_I = TypeVar("_I", bound=IntEnum)


class _Reader:
    """Typed access to CONFIG lines by number, recording which lines were consumed."""

    def __init__(self, lines: Iterable[ConfigLine]) -> None:
        self._lines = {line.number: line for line in lines}
        self._consumed: set[int] = set()

    def has(self, number: int) -> bool:
        return number in self._lines and cat.known(number)

    def text(self, number: int) -> str:
        line = self._lines.get(number)
        if line is None:
            raise ConfigFormatError(f"parameter {number:04d} ({cat.TOKENS[number].strip()}) is missing")
        self._consumed.add(number)
        return line.value

    def optional_text(self, number: int) -> str | None:
        return self.text(number) if self.has(number) else None

    def switch(self, number: int) -> bool:
        return self._flag(number, true="enable", false="disable")

    def yes_no(self, number: int) -> bool:
        return self._flag(number, true="yes", false="no")

    def integer(self, number: int) -> int:
        raw = self.text(number)
        if not raw.isascii() or not raw.isdigit():
            raise self._bad(number, raw, "a whole number")
        return int(raw)

    def address(self, number: int) -> IPv4Address:
        raw = self.text(number)
        try:
            return IPv4Address(raw)
        except AddressValueError as exc:
            raise self._bad(number, raw, "an IPv4 address") from exc

    def choice(self, number: int, enum_type: type[_E]) -> _E:
        raw = self.text(number)
        for member in enum_type:
            if str(member.value).lower() == raw.lower():
                return member
        allowed = ", ".join(str(member.value) for member in enum_type)
        raise self._bad(number, raw, f"one of {allowed}")

    def int_choice(self, number: int, enum_type: type[_I]) -> _I:
        value = self.integer(number)
        for member in enum_type:
            if member.value == value:
                return member
        allowed = ", ".join(str(member.value) for member in enum_type)
        raise self._bad(number, str(value), f"one of {allowed}")

    def present_slots(self, line_of: Iterable[tuple[int, int]]) -> list[int]:
        """Slots whose line exists, from ``(slot, line)`` pairs."""
        return [slot for slot, line in line_of if self.has(line)]

    def leftovers(self) -> tuple[ConfigLine, ...]:
        return tuple(line for number, line in sorted(self._lines.items()) if number not in self._consumed)

    def _flag(self, number: int, *, true: str, false: str) -> bool:
        raw = self.text(number)
        if raw.lower() in (true, false):
            return raw.lower() == true
        raise self._bad(number, raw, f"{true.capitalize()} or {false.capitalize()}")

    def _bad(self, number: int, raw: str, expected: str) -> ConfigFormatError:
        token = cat.TOKENS[number].strip()
        return ConfigFormatError(f"parameter {number:04d} ({token}) is {raw!r}, expected {expected}")


def read_config(lines: Iterable[ConfigLine]) -> DeviceConfig:
    """Build the typed configuration from parsed lines.

    Raises:
        ConfigFormatError: A required parameter is missing or a value is malformed.
    """
    reader = _Reader(lines)
    try:
        return _build(reader)
    except ValidationError as exc:
        details = "; ".join(_describe(exc.title, error) for error in exc.errors())
        raise ConfigFormatError(f"configuration values out of range: {details}") from exc


def _describe(model: str, error: ErrorDetails) -> str:
    # Our own sentence from the keys we report, never str(ValidationError): that carries
    # pydantic's type tags and a versioned documentation URL.
    location = ".".join([model, *(str(part) for part in error["loc"])])
    return f"{location}: {error['msg'].removeprefix('Value error, ')}"


def _build(reader: _Reader) -> DeviceConfig:
    # Keyword arguments are evaluated in order, so ``unmodeled`` collects what every group
    # before it left unread.
    return DeviceConfig(
        box_name=reader.text(cat.BOX_NAME),
        protocols=_protocols(reader),
        tcp_ip=_tcp_ip(reader),
        logical_printers=_logical_printers(reader),
        serial=_serial(reader),
        port_names=_slot_texts(reader, [(slot, cat.port_name_line(slot)) for slot in cat.SLOTS]),
        parallel_modes=_parallel_modes(reader),
        netware=_netware(reader),
        appletalk=_appletalk(reader),
        mail=_mail(reader),
        smb=_smb(reader),
        snmp=_snmp(reader),
        unmodeled=reader.leftovers(),
    )


def _protocols(reader: _Reader) -> Protocols:
    return Protocols(
        ipx_spx=reader.switch(cat.PROTOCOL_IPX_SPX),
        tcp_ip=reader.switch(cat.PROTOCOL_TCP_IP),
        appletalk=reader.switch(cat.PROTOCOL_APPLETALK),
        netbeui=reader.switch(cat.PROTOCOL_NETBEUI),
    )


def _serial(reader: _Reader) -> SerialPort | None:
    if not reader.has(cat.SERIAL_BAUD_RATE):
        return None
    return SerialPort(
        baud_rate=reader.int_choice(cat.SERIAL_BAUD_RATE, BaudRate),
        stop_bits=reader.int_choice(cat.SERIAL_STOP_BITS, StopBits),
        parity=reader.choice(cat.SERIAL_PARITY, Parity),
        data_bits=reader.int_choice(cat.SERIAL_DATA_BITS, DataBits),
        handshake=reader.choice(cat.SERIAL_HANDSHAKE, Handshake),
    )


def _logical_printers(reader: _Reader) -> tuple[LogicalPrinter, ...]:
    numbers = reader.present_slots((n, cat.printer_line(n, 0)) for n in range(1, 9))
    return tuple(_logical_printer(reader, number) for number in numbers)


def _logical_printer(reader: _Reader, number: int) -> LogicalPrinter:
    return LogicalPrinter(
        number=number,
        port=reader.choice(cat.printer_line(number, 0), PortId),
        pre_string=reader.text(cat.printer_line(number, 1)),
        post_string=reader.text(cat.printer_line(number, 2)),
        convert_lf=reader.yes_no(cat.printer_line(number, 3)),
        name=reader.optional_text(cat.printer_line(number, 4)),
    )


def _slot_texts(reader: _Reader, slot_lines: list[tuple[int, int]]) -> tuple[SlotText, ...]:
    lines = dict(slot_lines)
    return tuple(SlotText(slot=slot, value=reader.text(lines[slot])) for slot in reader.present_slots(slot_lines))


def _slot_flags(reader: _Reader, slot_lines: list[tuple[int, int]]) -> tuple[SlotFlag, ...]:
    lines = dict(slot_lines)
    return tuple(SlotFlag(slot=slot, enabled=reader.yes_no(lines[slot])) for slot in reader.present_slots(slot_lines))


def _parallel_modes(reader: _Reader) -> tuple[ParallelMode, ...]:
    slots = reader.present_slots((slot, cat.parallel_mode_line(slot)) for slot in cat.SLOTS)
    return tuple(ParallelMode(slot=slot, mode=reader.choice(cat.parallel_mode_line(slot), LptMode)) for slot in slots)


def _netware(reader: _Reader) -> NetWare | None:
    if not reader.has(cat.NETWARE_MODE):
        return None
    return NetWare(
        mode=reader.choice(cat.NETWARE_MODE, NetWareMode),
        frame_ethernet_ii=reader.switch(cat.NETWARE_FRAME_ETHERNET_II),
        frame_802_2=reader.switch(cat.NETWARE_FRAME_802_2),
        frame_802_3=reader.switch(cat.NETWARE_FRAME_802_3),
        frame_snap=reader.switch(cat.NETWARE_FRAME_SNAP),
        file_server=reader.text(cat.NETWARE_FILE_SERVER),
        notify=reader.yes_no(cat.NETWARE_NOTIFY),
        poll_interval=reader.integer(cat.NETWARE_POLL_INTERVAL),
        nds_tree=reader.optional_text(cat.NETWARE_NDS_TREE),
        nds_context=reader.optional_text(cat.NETWARE_NDS_CONTEXT),
        remote_printer_names=_slot_texts(reader, [(slot, cat.slot_line(2500, slot)) for slot in cat.SLOTS]),
    )


def _appletalk(reader: _Reader) -> AppleTalk | None:
    if not reader.has(cat.APPLETALK_ZONE):
        return None
    return AppleTalk(
        zone=reader.text(cat.APPLETALK_ZONE),
        printer_types=_slot_texts(reader, [(slot, cat.slot_line(3000, slot)) for slot in cat.SLOTS]),
        binary_protocol=_slot_flags(reader, [(slot, cat.slot_line(3100, slot)) for slot in cat.SLOTS]),
    )


def _tcp_ip(reader: _Reader) -> TcpIp:
    return TcpIp(
        ip_address=reader.address(cat.TCP_IP_ADDRESS),
        gateway=reader.address(cat.TCP_GATEWAY),
        netmask=reader.address(cat.TCP_NETMASK),
        retry_interval=reader.integer(cat.TCP_RETRY_INTERVAL),
        retry_count=reader.integer(cat.TCP_RETRY_COUNT),
        wins_server=reader.address(cat.TCP_WINS_SERVER) if reader.has(cat.TCP_WINS_SERVER) else None,
        dhcp=reader.switch(cat.TCP_DHCP) if reader.has(cat.TCP_DHCP) else None,
    )


def _mail(reader: _Reader) -> Mail | None:
    if not reader.has(cat.MAIL_SERVER):
        return None
    return Mail(
        server=reader.address(cat.mail_line(0)),
        account=reader.text(cat.mail_line(1)),
        password=reader.text(cat.mail_line(2)),
        check_interval=reader.integer(cat.mail_line(3)),
        banner=reader.yes_no(cat.mail_line(4)),
        redirect_account=reader.text(cat.mail_line(5)),
        port=reader.text(cat.mail_line(6)),
        print_every_mail=reader.yes_no(cat.mail_line(7)),
        notify=reader.yes_no(cat.mail_line(8)),
        printer_model=reader.text(cat.mail_line(9)),
    )


def _smb(reader: _Reader) -> Smb | None:
    if not reader.has(cat.SMB_WORKGROUP):
        return None
    return Smb(
        workgroup=reader.text(cat.SMB_WORKGROUP),
        drop_job_on_error=reader.yes_no(cat.SMB_DROP_JOB),
        delay=reader.integer(cat.SMB_DELAY),
        description=reader.optional_text(cat.SMB_DESCRIPTION),
    )


def _snmp(reader: _Reader) -> Snmp | None:
    if not reader.has(cat.SNMP_CONTACT):
        return None
    managers = reader.present_slots((slot, cat.manager_line(slot, 1)) for slot in cat.SLOTS)
    traps = reader.present_slots((slot, cat.trap_line(slot, 1)) for slot in cat.SLOTS)
    return Snmp(
        contact=reader.text(cat.SNMP_CONTACT),
        location=reader.text(cat.SNMP_LOCATION),
        managers=tuple(_manager(reader, slot) for slot in managers),
        traps=tuple(_trap(reader, slot) for slot in traps),
    )


def _manager(reader: _Reader, slot: int) -> SnmpManager:
    return SnmpManager(
        slot=slot,
        address=reader.address(cat.manager_line(slot, 1)),
        access=reader.choice(cat.manager_line(slot, 2), AccessRight),
        community=reader.text(cat.manager_line(slot, 3)),
    )


def _trap(reader: _Reader, slot: int) -> SnmpTrap:
    return SnmpTrap(
        slot=slot,
        address=reader.address(cat.trap_line(slot, 1)),
        severity=reader.integer(cat.trap_line(slot, 2)),
        community=reader.text(cat.trap_line(slot, 3)),
        enabled=reader.switch(cat.trap_line(slot, 4)),
    )


__all__ = ["read_config"]
