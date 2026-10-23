"""Write a :class:`~.config_model.DeviceConfig` back to CONFIG lines.

The inverse of :mod:`.config_reader`: each value is spelled exactly as the firmware prints it
(``Enable``, ``Yes``, ``Read Only``, ``XON/XOFF``), and every line carries the token from
:mod:`.config_catalogue`, so writing back an unchanged configuration reproduces the device's
file byte for byte.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import config_catalogue as cat
from .config_lines import ConfigLine
from .errors import ConfigFormatError

if TYPE_CHECKING:
    from enum import Enum, IntEnum
    from ipaddress import IPv4Address

    from .config_model import (
        AppleTalk,
        DeviceConfig,
        LogicalPrinter,
        Mail,
        NetWare,
        SerialPort,
        SlotFlag,
        SlotText,
        Smb,
        Snmp,
        TcpIp,
    )


class _Writer:
    """Collects CONFIG lines, spelling each value type the way the firmware does."""

    def __init__(self) -> None:
        self.lines: list[ConfigLine] = []

    def text(self, number: int, value: str) -> None:
        if not cat.known(number):
            raise ConfigFormatError(f"parameter {number:04d} does not exist on this device family")
        self.lines.append(ConfigLine(number=number, token=cat.TOKENS[number], value=value))

    def switch(self, number: int, *, value: bool) -> None:
        self.text(number, "Enable" if value else "Disable")

    def yes_no(self, number: int, *, value: bool) -> None:
        self.text(number, "Yes" if value else "No")

    def integer(self, number: int, value: int) -> None:
        self.text(number, str(value))

    def address(self, number: int, value: IPv4Address) -> None:
        self.text(number, str(value))

    def choice(self, number: int, value: Enum) -> None:
        self.text(number, str(value.value))

    def int_choice(self, number: int, value: IntEnum) -> None:
        self.text(number, str(value.value))


def write_config(config: DeviceConfig) -> tuple[ConfigLine, ...]:
    """Return the CONFIG lines for ``config``, sorted by line number."""
    writer = _Writer()
    writer.text(cat.BOX_NAME, config.box_name)
    _protocols(writer, config)
    _serial(writer, config.serial)
    _port_names(writer, config.port_names)
    for printer in config.logical_printers:
        _logical_printer(writer, printer)
    for mode in config.parallel_modes:
        writer.choice(cat.parallel_mode_line(mode.slot), mode.mode)
    _netware(writer, config.netware)
    _appletalk(writer, config.appletalk)
    _tcp_ip(writer, config.tcp_ip)
    _mail(writer, config.mail)
    _smb(writer, config.smb)
    _snmp(writer, config.snmp)
    return tuple(sorted([*writer.lines, *config.unmodeled], key=lambda line: line.number))


def _protocols(writer: _Writer, config: DeviceConfig) -> None:
    writer.switch(cat.PROTOCOL_IPX_SPX, value=config.protocols.ipx_spx)
    writer.switch(cat.PROTOCOL_TCP_IP, value=config.protocols.tcp_ip)
    writer.switch(cat.PROTOCOL_APPLETALK, value=config.protocols.appletalk)
    writer.switch(cat.PROTOCOL_NETBEUI, value=config.protocols.netbeui)


def _serial(writer: _Writer, serial: SerialPort | None) -> None:
    if serial is None:
        return
    writer.int_choice(cat.SERIAL_BAUD_RATE, serial.baud_rate)
    writer.int_choice(cat.SERIAL_STOP_BITS, serial.stop_bits)
    writer.choice(cat.SERIAL_PARITY, serial.parity)
    writer.int_choice(cat.SERIAL_DATA_BITS, serial.data_bits)
    writer.choice(cat.SERIAL_HANDSHAKE, serial.handshake)


def _port_names(writer: _Writer, names: tuple[SlotText, ...]) -> None:
    for name in names:
        writer.text(cat.port_name_line(name.slot), name.value)


def _logical_printer(writer: _Writer, printer: LogicalPrinter) -> None:
    writer.choice(cat.printer_line(printer.number, 0), printer.port)
    writer.text(cat.printer_line(printer.number, 1), printer.pre_string)
    writer.text(cat.printer_line(printer.number, 2), printer.post_string)
    writer.yes_no(cat.printer_line(printer.number, 3), value=printer.convert_lf)
    if printer.name is not None:
        writer.text(cat.printer_line(printer.number, 4), printer.name)


def _slot_texts(writer: _Writer, base: int, items: tuple[SlotText, ...]) -> None:
    for item in items:
        writer.text(cat.slot_line(base, item.slot), item.value)


def _slot_flags(writer: _Writer, base: int, items: tuple[SlotFlag, ...]) -> None:
    for item in items:
        writer.yes_no(cat.slot_line(base, item.slot), value=item.enabled)


def _netware(writer: _Writer, netware: NetWare | None) -> None:
    if netware is None:
        return
    writer.choice(cat.NETWARE_MODE, netware.mode)
    writer.switch(cat.NETWARE_FRAME_ETHERNET_II, value=netware.frame_ethernet_ii)
    writer.switch(cat.NETWARE_FRAME_802_2, value=netware.frame_802_2)
    writer.switch(cat.NETWARE_FRAME_802_3, value=netware.frame_802_3)
    writer.switch(cat.NETWARE_FRAME_SNAP, value=netware.frame_snap)
    writer.text(cat.NETWARE_FILE_SERVER, netware.file_server)
    writer.yes_no(cat.NETWARE_NOTIFY, value=netware.notify)
    writer.integer(cat.NETWARE_POLL_INTERVAL, netware.poll_interval)
    if netware.nds_tree is not None:
        writer.text(cat.NETWARE_NDS_TREE, netware.nds_tree)
    if netware.nds_context is not None:
        writer.text(cat.NETWARE_NDS_CONTEXT, netware.nds_context)
    _slot_texts(writer, 2500, netware.remote_printer_names)


def _appletalk(writer: _Writer, appletalk: AppleTalk | None) -> None:
    if appletalk is None:
        return
    writer.text(cat.APPLETALK_ZONE, appletalk.zone)
    _slot_texts(writer, 3000, appletalk.printer_types)
    _slot_flags(writer, 3100, appletalk.binary_protocol)


def _tcp_ip(writer: _Writer, tcp_ip: TcpIp) -> None:
    writer.address(cat.TCP_IP_ADDRESS, tcp_ip.ip_address)
    writer.address(cat.TCP_GATEWAY, tcp_ip.gateway)
    writer.address(cat.TCP_NETMASK, tcp_ip.netmask)
    writer.integer(cat.TCP_RETRY_INTERVAL, tcp_ip.retry_interval)
    writer.integer(cat.TCP_RETRY_COUNT, tcp_ip.retry_count)
    if tcp_ip.wins_server is not None:
        writer.address(cat.TCP_WINS_SERVER, tcp_ip.wins_server)
    if tcp_ip.dhcp is not None:
        writer.switch(cat.TCP_DHCP, value=tcp_ip.dhcp)


def _mail(writer: _Writer, mail: Mail | None) -> None:
    if mail is None:
        return
    writer.address(cat.mail_line(0), mail.server)
    writer.text(cat.mail_line(1), mail.account)
    writer.text(cat.mail_line(2), mail.password)
    writer.integer(cat.mail_line(3), mail.check_interval)
    writer.yes_no(cat.mail_line(4), value=mail.banner)
    writer.text(cat.mail_line(5), mail.redirect_account)
    writer.text(cat.mail_line(6), mail.port)
    writer.yes_no(cat.mail_line(7), value=mail.print_every_mail)
    writer.yes_no(cat.mail_line(8), value=mail.notify)
    writer.text(cat.mail_line(9), mail.printer_model)


def _smb(writer: _Writer, smb: Smb | None) -> None:
    if smb is None:
        return
    writer.text(cat.SMB_WORKGROUP, smb.workgroup)
    writer.yes_no(cat.SMB_DROP_JOB, value=smb.drop_job_on_error)
    writer.integer(cat.SMB_DELAY, smb.delay)
    if smb.description is not None:
        writer.text(cat.SMB_DESCRIPTION, smb.description)


def _snmp(writer: _Writer, snmp: Snmp | None) -> None:
    if snmp is None:
        return
    writer.text(cat.SNMP_CONTACT, snmp.contact)
    writer.text(cat.SNMP_LOCATION, snmp.location)
    for manager in snmp.managers:
        writer.address(cat.manager_line(manager.slot, 1), manager.address)
        writer.choice(cat.manager_line(manager.slot, 2), manager.access)
        writer.text(cat.manager_line(manager.slot, 3), manager.community)
    for trap in snmp.traps:
        writer.address(cat.trap_line(trap.slot, 1), trap.address)
        writer.integer(cat.trap_line(trap.slot, 2), trap.severity)
        writer.text(cat.trap_line(trap.slot, 3), trap.community)
        writer.switch(cat.trap_line(trap.slot, 4), value=trap.enabled)


__all__ = ["write_config"]
