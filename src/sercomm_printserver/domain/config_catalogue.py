"""Line numbers and tokens of the CONFIG parameters this package models.

A CONFIG line reads ``NNNN TOKEN:VALUE``. The line number identifies the parameter; the token
is a label the device prints in front of it. Extracted from ten vendor firmware images and a
real PS301 (``docs/config-keys.md``): one line number carries the same token in every image,
so one table serves all models. Lines 0042 and 0503 come from the TRENDnet manual only.

Trailing spaces are part of a token (``"TCPIP_P "``): the device prints them, and rendering
them back keeps a written CONFIG byte-identical to the one read.

A line that is not in this table is not modelled; it travels unchanged in
:attr:`~sercomm_printserver.domain.config_model.DeviceConfig.unmodeled`.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

TOKENS: Final = MappingProxyType(
    {
        1: "BOX_NAME",
        11: "IPXSPX_P",
        12: "TCPIP_P ",
        13: "APTALK_P",
        14: "NETB_P",
        30: "BAUDRATE",
        31: "STOPBITS",
        32: "PARITY  ",
        33: "DATABITS",
        34: "HANDSHAK",
        40: "P1_NAME",
        41: "P2_NAME",
        42: "P3_NAME",
        100: "L1_PROUT",
        101: "L1_PREST",
        102: "L1_POSTR",
        103: "L1_CHGLF",
        104: "L1_NAME",
        120: "L2_PROUT",
        121: "L2_PREST",
        122: "L2_POSTR",
        123: "L2_CHGLF",
        124: "L2_NAME",
        140: "L3_PROUT",
        141: "L3_PREST",
        142: "L3_POSTR",
        143: "L3_CHGLF",
        144: "L3_NAME",
        160: "L4_PROUT",
        161: "L4_PREST",
        162: "L4_POSTR",
        163: "L4_CHGLF",
        164: "L4_NAME",
        180: "L5_PROUT",
        181: "L5_PREST",
        182: "L5_POSTR",
        183: "L5_CHGLF",
        184: "L5_NAME",
        200: "L6_PROUT",
        201: "L6_PREST",
        202: "L6_POSTR",
        203: "L6_CHGLF",
        204: "L6_NAME",
        220: "L7_PROUT",
        221: "L7_PREST",
        222: "L7_POSTR",
        223: "L7_CHGLF",
        224: "L7_NAME",
        240: "L8_PROUT",
        241: "L8_PREST",
        242: "L8_POSTR",
        243: "L8_CHGLF",
        244: "L8_NAME",
        501: "LPT1MODE",
        502: "LPT2MODE",
        503: "LPT3MODE",
        504: "LPT3MODE",
        2000: "NOP_MODE",
        2001: "NFREthII",
        2002: "NFR802.2",
        2003: "NFR802.3",
        2004: "NFRSNAP ",
        2101: "NFS_NAME",
        2102: "N_NOTIFY",
        2103: "N_FREQ  ",
        2110: "NDS_TREE",
        2111: "NCONTEXT",
        2501: "NR_NAME1",
        2502: "NR_NAME2",
        2503: "NR_NAME3",
        2504: "NR_NAME4",
        3000: "AP_ZONE",
        3001: "AP_TYPE1",
        3002: "AP_TYPE2",
        3003: "AP_TYPE3",
        3004: "AP_TYPE4",
        3101: "AP_PCOMM1",
        3102: "AP_PCOMM2",
        3103: "AP_PCOMM3",
        3104: "AP_PCOMM4",
        4000: "IP_ADDR",
        4001: "GATEWAY",
        4002: "MASK   ",
        4010: "TCP_INT",
        4011: "TCP_CNT",
        4012: "WINS_IP",
        4020: "DHCP_MODE",
        4100: "MAIL_IP",
        4101: "MAIL_ACC",
        4102: "MAIL_PAS",
        4103: "MAIL_INT",
        4104: "MAIL_BAN",
        4105: "MAIL_RED",
        4106: "MAIL_POR",
        4107: "MAIL_EVR",
        4108: "MAIL_NOT",
        4109: "MAIL_MOD",
        5000: "SMBGNAME",
        5001: "SMBDROP",
        5002: "SMBDELAY",
        5003: "SMBDESC",
        6000: "CONTACT",
        6001: "LOCATION",
        6011: "M1_IP",
        6012: "M1_ACCP",
        6013: "M1_CSTR",
        6021: "M2_IP",
        6022: "M2_ACCP",
        6023: "M2_CSTR",
        6031: "M3_IP",
        6032: "M3_ACCP",
        6033: "M3_CSTR",
        6041: "M4_IP",
        6042: "M4_ACCP",
        6043: "M4_CSTR",
        6111: "T1_IP",
        6112: "T1_S",
        6113: "T1_CSTR",
        6114: "T1_ENAB",
        6121: "T2_IP",
        6122: "T2_S",
        6123: "T2_CSTR",
        6124: "T2_ENAB",
        6131: "T3_IP",
        6132: "T3_S",
        6133: "T3_CSTR",
        6134: "T3_ENAB",
        6141: "T4_IP",
        6142: "T4_S",
        6143: "T4_CSTR",
        6144: "T4_ENAB",
    }
)

BOX_NAME: Final = 1
PROTOCOL_IPX_SPX: Final = 11
PROTOCOL_TCP_IP: Final = 12
PROTOCOL_APPLETALK: Final = 13
PROTOCOL_NETBEUI: Final = 14
SERIAL_BAUD_RATE: Final = 30
SERIAL_STOP_BITS: Final = 31
SERIAL_PARITY: Final = 32
SERIAL_DATA_BITS: Final = 33
SERIAL_HANDSHAKE: Final = 34
NETWARE_MODE: Final = 2000
NETWARE_FRAME_ETHERNET_II: Final = 2001
NETWARE_FRAME_802_2: Final = 2002
NETWARE_FRAME_802_3: Final = 2003
NETWARE_FRAME_SNAP: Final = 2004
NETWARE_FILE_SERVER: Final = 2101
NETWARE_NOTIFY: Final = 2102
NETWARE_POLL_INTERVAL: Final = 2103
NETWARE_NDS_TREE: Final = 2110
NETWARE_NDS_CONTEXT: Final = 2111
APPLETALK_ZONE: Final = 3000
TCP_IP_ADDRESS: Final = 4000
TCP_GATEWAY: Final = 4001
TCP_NETMASK: Final = 4002
TCP_RETRY_INTERVAL: Final = 4010
TCP_RETRY_COUNT: Final = 4011
TCP_WINS_SERVER: Final = 4012
TCP_DHCP: Final = 4020
MAIL_SERVER: Final = 4100
SMB_WORKGROUP: Final = 5000
SMB_DROP_JOB: Final = 5001
SMB_DELAY: Final = 5002
SMB_DESCRIPTION: Final = 5003
SNMP_CONTACT: Final = 6000
SNMP_LOCATION: Final = 6001

#: Slots a per-port or per-station parameter can have. The table decides which exist.
SLOTS: Final = range(1, 10)


def port_name_line(slot: int) -> int:
    """Line of ``P<slot>_NAME``.

    Example:
        >>> port_name_line(2)
        41
    """
    return 39 + slot


def printer_line(number: int, offset: int) -> int:
    """Line of a logical-printer parameter: offset 0 port, 1 pre-string, 2 post-string, 3 LF, 4 name.

    Example:
        >>> printer_line(3, 0), printer_line(8, 3)
        (140, 243)
    """
    return 100 + 20 * (number - 1) + offset


def parallel_mode_line(slot: int) -> int:
    """Line of ``LPT<n>MODE`` for a slot.

    Example:
        >>> parallel_mode_line(1)
        501
    """
    return 500 + slot


def slot_line(base: int, slot: int) -> int:
    """Line of a per-slot parameter whose slot 1 sits at ``base + 1`` (NetWare, AppleTalk).

    Example:
        >>> slot_line(2500, 3)
        2503
    """
    return base + slot


def mail_line(offset: int) -> int:
    """Line of the mail parameter at ``offset`` (0 server ... 9 printer model)."""
    return MAIL_SERVER + offset


def manager_line(slot: int, offset: int) -> int:
    """Line of an SNMP manager parameter: offset 1 address, 2 access, 3 community.

    Example:
        >>> manager_line(4, 3)
        6043
    """
    return 6000 + 10 * slot + offset


def trap_line(slot: int, offset: int) -> int:
    """Line of an SNMP trap parameter: offset 1 address, 2 severity, 3 community, 4 enabled.

    Example:
        >>> trap_line(1, 4)
        6114
    """
    return 6100 + 10 * slot + offset


def known(line: int) -> bool:
    """Whether ``line`` is a parameter this package models.

    Example:
        >>> known(1), known(7000)
        (True, False)
    """
    return line in TOKENS


__all__ = [
    "APPLETALK_ZONE",
    "BOX_NAME",
    "MAIL_SERVER",
    "NETWARE_FILE_SERVER",
    "NETWARE_FRAME_802_2",
    "NETWARE_FRAME_802_3",
    "NETWARE_FRAME_ETHERNET_II",
    "NETWARE_FRAME_SNAP",
    "NETWARE_MODE",
    "NETWARE_NDS_CONTEXT",
    "NETWARE_NDS_TREE",
    "NETWARE_NOTIFY",
    "NETWARE_POLL_INTERVAL",
    "PROTOCOL_APPLETALK",
    "PROTOCOL_IPX_SPX",
    "PROTOCOL_NETBEUI",
    "PROTOCOL_TCP_IP",
    "SERIAL_BAUD_RATE",
    "SERIAL_DATA_BITS",
    "SERIAL_HANDSHAKE",
    "SERIAL_PARITY",
    "SERIAL_STOP_BITS",
    "SLOTS",
    "SMB_DELAY",
    "SMB_DESCRIPTION",
    "SMB_DROP_JOB",
    "SMB_WORKGROUP",
    "SNMP_CONTACT",
    "SNMP_LOCATION",
    "TCP_DHCP",
    "TCP_GATEWAY",
    "TCP_IP_ADDRESS",
    "TCP_NETMASK",
    "TCP_RETRY_COUNT",
    "TCP_RETRY_INTERVAL",
    "TCP_WINS_SERVER",
    "TOKENS",
    "known",
    "mail_line",
    "manager_line",
    "parallel_mode_line",
    "port_name_line",
    "printer_line",
    "slot_line",
    "trap_line",
]
