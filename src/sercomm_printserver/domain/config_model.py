"""Typed model of a print server's CONFIG file.

Which parameters a device has depends on its model and firmware (``docs/config-keys.md``), so
every group that is not universal is optional and a slotted setting is a tuple holding the
slots the device actually reported. A parameter the catalogue does not model is kept verbatim
in :attr:`DeviceConfig.unmodeled` and written back at its line, so writing a configuration
never drops a setting this package does not understand.
"""

from __future__ import annotations

from ipaddress import IPv4Address

from pydantic import BaseModel

from .config_lines import ConfigLine
from .config_types import (
    AccessRight,
    BaudRate,
    BoxName,
    Byte,
    DataBits,
    Handshake,
    HexString,
    LptMode,
    NetWareMode,
    Parity,
    PortId,
    Severity,
    Slot,
    StopBits,
    Text7,
    Text15,
    Text19,
    Text31,
    Text39,
    Text47,
    Text235,
    Word,
)


class _Frozen(BaseModel, frozen=True, extra="forbid"):
    """Immutable, closed model: an unexpected field is a bug, never data to keep."""


class Protocols(_Frozen, frozen=True):
    """Network protocol stacks switched on (lines 0011-0014)."""

    ipx_spx: bool
    tcp_ip: bool
    appletalk: bool
    netbeui: bool


class SerialPort(_Frozen, frozen=True):
    """Serial port settings (lines 0030-0034), present on models with a serial port."""

    baud_rate: BaudRate
    stop_bits: StopBits
    parity: Parity
    data_bits: DataBits
    handshake: Handshake


class LogicalPrinter(_Frozen, frozen=True):
    """Logical printer ``L<number>``: the queue name used by LPD (lines 0100-0244)."""

    number: Slot
    port: PortId
    pre_string: HexString
    post_string: HexString
    convert_lf: bool
    name: Text19 | None = None


class SlotText(_Frozen, frozen=True):
    """A text setting that exists once per port slot, such as a printer type."""

    slot: Slot
    value: Text19


class SlotFlag(_Frozen, frozen=True):
    """A yes/no setting that exists once per port slot."""

    slot: Slot
    enabled: bool


class ParallelMode(_Frozen, frozen=True):
    """Handshake check of one parallel port slot (lines 0501-0504)."""

    slot: Slot
    mode: LptMode


class NetWare(_Frozen, frozen=True):
    """NetWare settings (lines 2000-2504)."""

    mode: NetWareMode
    frame_ethernet_ii: bool
    frame_802_2: bool
    frame_802_3: bool
    frame_snap: bool
    file_server: Text19
    notify: bool
    poll_interval: Byte
    nds_tree: Text39 | None = None
    nds_context: Text235 | None = None
    remote_printer_names: tuple[SlotText, ...] = ()


class AppleTalk(_Frozen, frozen=True):
    """AppleTalk settings (lines 3000-3104)."""

    zone: Text19
    printer_types: tuple[SlotText, ...] = ()
    binary_protocol: tuple[SlotFlag, ...] = ()


class TcpIp(_Frozen, frozen=True):
    """TCP/IP settings (lines 4000-4020); firmware 6A10 has no WINS server and no DHCP switch."""

    ip_address: IPv4Address
    gateway: IPv4Address
    netmask: IPv4Address
    retry_interval: Byte
    retry_count: Byte
    wins_server: IPv4Address | None = None
    dhcp: bool | None = None


class Mail(_Frozen, frozen=True):
    """POP3 mail printing (lines 4100-4109), absent on some firmware.

    The device reads ``password`` back masked with asterisks.
    """

    server: IPv4Address
    account: Text19
    password: Text19
    check_interval: Word
    banner: bool
    redirect_account: Text19
    port: Text19
    print_every_mail: bool
    notify: bool
    printer_model: Text19


class Smb(_Frozen, frozen=True):
    """Windows (NetBEUI/SMB) printing (lines 5000-5003)."""

    workgroup: Text15
    drop_job_on_error: bool
    delay: Byte
    description: Text47 | None = None


class SnmpManager(_Frozen, frozen=True):
    """SNMP management station ``M<slot>`` (lines 6011-6043)."""

    slot: Slot
    address: IPv4Address
    access: AccessRight
    community: Text7


class SnmpTrap(_Frozen, frozen=True):
    """SNMP trap receiver ``T<slot>`` (lines 6111-6144)."""

    slot: Slot
    address: IPv4Address
    severity: Severity
    community: Text7
    enabled: bool


class Snmp(_Frozen, frozen=True):
    """SNMP settings (lines 6000-6144)."""

    contact: Text31
    location: Text31
    managers: tuple[SnmpManager, ...] = ()
    traps: tuple[SnmpTrap, ...] = ()


class DeviceConfig(_Frozen, frozen=True):
    """Everything a device reported in its CONFIG file, typed.

    Example:
        >>> from pathlib import Path
        >>> from sercomm_printserver.domain.config_codec import parse_config
        >>> text = Path("docs/device-dump/CONFIG.txt").read_text(encoding="ascii")
        >>> config = parse_config(text)
        >>> config.box_name, config.logical_printers[2].port.value
        ('PS_EXAMPLE', 'SP')
    """

    box_name: BoxName
    protocols: Protocols
    tcp_ip: TcpIp
    logical_printers: tuple[LogicalPrinter, ...]
    serial: SerialPort | None = None
    port_names: tuple[SlotText, ...] = ()
    parallel_modes: tuple[ParallelMode, ...] = ()
    netware: NetWare | None = None
    appletalk: AppleTalk | None = None
    mail: Mail | None = None
    smb: Smb | None = None
    snmp: Snmp | None = None
    unmodeled: tuple[ConfigLine, ...] = ()
    """Lines this package does not model, written back unchanged at their line number."""


__all__ = [
    "AppleTalk",
    "DeviceConfig",
    "LogicalPrinter",
    "Mail",
    "NetWare",
    "ParallelMode",
    "Protocols",
    "SerialPort",
    "SlotFlag",
    "SlotText",
    "Smb",
    "Snmp",
    "SnmpManager",
    "SnmpTrap",
    "TcpIp",
]
