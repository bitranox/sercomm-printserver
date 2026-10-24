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
    writer.text(cat.ParameterLine.BOX_NAME, config.box_name)
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
    writer.switch(cat.ParameterLine.PROTOCOL_IPX_SPX, value=config.protocols.ipx_spx)
    writer.switch(cat.ParameterLine.PROTOCOL_TCP_IP, value=config.protocols.tcp_ip)
    writer.switch(cat.ParameterLine.PROTOCOL_APPLETALK, value=config.protocols.appletalk)
    writer.switch(cat.ParameterLine.PROTOCOL_NETBEUI, value=config.protocols.netbeui)


def _serial(writer: _Writer, serial: SerialPort | None) -> None:
    if serial is None:
        return
    writer.int_choice(cat.ParameterLine.SERIAL_BAUD_RATE, serial.baud_rate)
    writer.int_choice(cat.ParameterLine.SERIAL_STOP_BITS, serial.stop_bits)
    writer.choice(cat.ParameterLine.SERIAL_PARITY, serial.parity)
    writer.int_choice(cat.ParameterLine.SERIAL_DATA_BITS, serial.data_bits)
    writer.choice(cat.ParameterLine.SERIAL_HANDSHAKE, serial.handshake)


def _port_names(writer: _Writer, names: tuple[SlotText, ...]) -> None:
    for name in names:
        writer.text(cat.port_name_line(name.slot), name.value)


def _logical_printer(writer: _Writer, printer: LogicalPrinter) -> None:
    writer.choice(cat.printer_line(printer.number, cat.PrinterField.PORT), printer.port)
    writer.text(cat.printer_line(printer.number, cat.PrinterField.PRE_STRING), printer.pre_string)
    writer.text(cat.printer_line(printer.number, cat.PrinterField.POST_STRING), printer.post_string)
    writer.yes_no(cat.printer_line(printer.number, cat.PrinterField.CONVERT_LF), value=printer.convert_lf)
    if printer.name is not None:
        writer.text(cat.printer_line(printer.number, cat.PrinterField.NAME), printer.name)


def _slot_texts(writer: _Writer, block: cat.SlotBlock, items: tuple[SlotText, ...]) -> None:
    for item in items:
        writer.text(cat.slot_line(block, item.slot), item.value)


def _slot_flags(writer: _Writer, block: cat.SlotBlock, items: tuple[SlotFlag, ...]) -> None:
    for item in items:
        writer.yes_no(cat.slot_line(block, item.slot), value=item.enabled)


def _netware(writer: _Writer, netware: NetWare | None) -> None:
    if netware is None:
        return
    writer.choice(cat.ParameterLine.NETWARE_MODE, netware.mode)
    writer.switch(cat.ParameterLine.NETWARE_FRAME_ETHERNET_II, value=netware.frame_ethernet_ii)
    writer.switch(cat.ParameterLine.NETWARE_FRAME_802_2, value=netware.frame_802_2)
    writer.switch(cat.ParameterLine.NETWARE_FRAME_802_3, value=netware.frame_802_3)
    writer.switch(cat.ParameterLine.NETWARE_FRAME_SNAP, value=netware.frame_snap)
    writer.text(cat.ParameterLine.NETWARE_FILE_SERVER, netware.file_server)
    writer.yes_no(cat.ParameterLine.NETWARE_NOTIFY, value=netware.notify)
    writer.integer(cat.ParameterLine.NETWARE_POLL_INTERVAL, netware.poll_interval)
    if netware.nds_tree is not None:
        writer.text(cat.ParameterLine.NETWARE_NDS_TREE, netware.nds_tree)
    if netware.nds_context is not None:
        writer.text(cat.ParameterLine.NETWARE_NDS_CONTEXT, netware.nds_context)
    _slot_texts(writer, cat.SlotBlock.NETWARE_REMOTE_PRINTER_NAMES, netware.remote_printer_names)


def _appletalk(writer: _Writer, appletalk: AppleTalk | None) -> None:
    if appletalk is None:
        return
    writer.text(cat.ParameterLine.APPLETALK_ZONE, appletalk.zone)
    _slot_texts(writer, cat.SlotBlock.APPLETALK_PRINTER_TYPES, appletalk.printer_types)
    _slot_flags(writer, cat.SlotBlock.APPLETALK_BINARY_PROTOCOL, appletalk.binary_protocol)


def _tcp_ip(writer: _Writer, tcp_ip: TcpIp) -> None:
    writer.address(cat.ParameterLine.TCP_IP_ADDRESS, tcp_ip.ip_address)
    writer.address(cat.ParameterLine.TCP_GATEWAY, tcp_ip.gateway)
    writer.address(cat.ParameterLine.TCP_NETMASK, tcp_ip.netmask)
    writer.integer(cat.ParameterLine.TCP_RETRY_INTERVAL, tcp_ip.retry_interval)
    writer.integer(cat.ParameterLine.TCP_RETRY_COUNT, tcp_ip.retry_count)
    if tcp_ip.wins_server is not None:
        writer.address(cat.ParameterLine.TCP_WINS_SERVER, tcp_ip.wins_server)
    if tcp_ip.dhcp is not None:
        writer.switch(cat.ParameterLine.TCP_DHCP, value=tcp_ip.dhcp)


def _mail(writer: _Writer, mail: Mail | None) -> None:
    if mail is None:
        return
    writer.address(cat.mail_line(cat.MailField.SERVER), mail.server)
    writer.text(cat.mail_line(cat.MailField.ACCOUNT), mail.account)
    writer.text(cat.mail_line(cat.MailField.PASSWORD), mail.password)
    writer.integer(cat.mail_line(cat.MailField.CHECK_INTERVAL), mail.check_interval)
    writer.yes_no(cat.mail_line(cat.MailField.BANNER), value=mail.banner)
    writer.text(cat.mail_line(cat.MailField.REDIRECT_ACCOUNT), mail.redirect_account)
    writer.text(cat.mail_line(cat.MailField.PORT), mail.port)
    writer.yes_no(cat.mail_line(cat.MailField.PRINT_EVERY_MAIL), value=mail.print_every_mail)
    writer.yes_no(cat.mail_line(cat.MailField.NOTIFY), value=mail.notify)
    writer.text(cat.mail_line(cat.MailField.PRINTER_MODEL), mail.printer_model)


def _smb(writer: _Writer, smb: Smb | None) -> None:
    if smb is None:
        return
    writer.text(cat.ParameterLine.SMB_WORKGROUP, smb.workgroup)
    writer.yes_no(cat.ParameterLine.SMB_DROP_JOB, value=smb.drop_job_on_error)
    writer.integer(cat.ParameterLine.SMB_DELAY, smb.delay)
    if smb.description is not None:
        writer.text(cat.ParameterLine.SMB_DESCRIPTION, smb.description)


def _snmp(writer: _Writer, snmp: Snmp | None) -> None:
    if snmp is None:
        return
    writer.text(cat.ParameterLine.SNMP_CONTACT, snmp.contact)
    writer.text(cat.ParameterLine.SNMP_LOCATION, snmp.location)
    for manager in snmp.managers:
        writer.address(cat.manager_line(manager.slot, cat.ManagerField.ADDRESS), manager.address)
        writer.choice(cat.manager_line(manager.slot, cat.ManagerField.ACCESS), manager.access)
        writer.text(cat.manager_line(manager.slot, cat.ManagerField.COMMUNITY), manager.community)
    for trap in snmp.traps:
        writer.address(cat.trap_line(trap.slot, cat.TrapField.ADDRESS), trap.address)
        writer.integer(cat.trap_line(trap.slot, cat.TrapField.SEVERITY), trap.severity)
        writer.text(cat.trap_line(trap.slot, cat.TrapField.COMMUNITY), trap.community)
        writer.switch(cat.trap_line(trap.slot, cat.TrapField.ENABLED), value=trap.enabled)


__all__ = ["write_config"]
