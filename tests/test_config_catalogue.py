"""Line numbers the catalogue's field enums resolve to.

The expected numbers were computed from the catalogue while its offsets were still bare ints, so
these tables pin that naming the offsets moved no parameter to another line. The token check
proves each member names the parameter its name says: a swapped pair of members would still
produce valid line numbers, but under the wrong token.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sercomm_printserver.domain import config_catalogue as cat
from sercomm_printserver.domain.config_catalogue import (
    MailField,
    ManagerField,
    ParameterLine,
    PrinterField,
    SlotBlock,
    TrapField,
)

if TYPE_CHECKING:
    from enum import IntEnum

# Computed from the catalogue while these lines were still loose module-level ints.
_PARAMETER_LINES = (
    ("BOX_NAME", 1, "BOX_NAME"),
    ("PROTOCOL_IPX_SPX", 11, "IPXSPX_P"),
    ("PROTOCOL_TCP_IP", 12, "TCPIP_P "),
    ("PROTOCOL_APPLETALK", 13, "APTALK_P"),
    ("PROTOCOL_NETBEUI", 14, "NETB_P"),
    ("SERIAL_BAUD_RATE", 30, "BAUDRATE"),
    ("SERIAL_STOP_BITS", 31, "STOPBITS"),
    ("SERIAL_PARITY", 32, "PARITY  "),
    ("SERIAL_DATA_BITS", 33, "DATABITS"),
    ("SERIAL_HANDSHAKE", 34, "HANDSHAK"),
    ("NETWARE_MODE", 2000, "NOP_MODE"),
    ("NETWARE_FRAME_ETHERNET_II", 2001, "NFREthII"),
    ("NETWARE_FRAME_802_2", 2002, "NFR802.2"),
    ("NETWARE_FRAME_802_3", 2003, "NFR802.3"),
    ("NETWARE_FRAME_SNAP", 2004, "NFRSNAP "),
    ("NETWARE_FILE_SERVER", 2101, "NFS_NAME"),
    ("NETWARE_NOTIFY", 2102, "N_NOTIFY"),
    ("NETWARE_POLL_INTERVAL", 2103, "N_FREQ  "),
    ("NETWARE_NDS_TREE", 2110, "NDS_TREE"),
    ("NETWARE_NDS_CONTEXT", 2111, "NCONTEXT"),
    ("APPLETALK_ZONE", 3000, "AP_ZONE"),
    ("TCP_IP_ADDRESS", 4000, "IP_ADDR"),
    ("TCP_GATEWAY", 4001, "GATEWAY"),
    ("TCP_NETMASK", 4002, "MASK   "),
    ("TCP_RETRY_INTERVAL", 4010, "TCP_INT"),
    ("TCP_RETRY_COUNT", 4011, "TCP_CNT"),
    ("TCP_WINS_SERVER", 4012, "WINS_IP"),
    ("TCP_DHCP", 4020, "DHCP_MODE"),
    ("MAIL_SERVER", 4100, "MAIL_IP"),
    ("SMB_WORKGROUP", 5000, "SMBGNAME"),
    ("SMB_DROP_JOB", 5001, "SMBDROP"),
    ("SMB_DELAY", 5002, "SMBDELAY"),
    ("SMB_DESCRIPTION", 5003, "SMBDESC"),
    ("SNMP_CONTACT", 6000, "CONTACT"),
    ("SNMP_LOCATION", 6001, "LOCATION"),
)

# The slot-1 line and token of each block: the token proves a base points at the block its name says.
_SLOT_BLOCKS = (
    (SlotBlock.NETWARE_REMOTE_PRINTER_NAMES, 2501, "NR_NAME1"),
    (SlotBlock.APPLETALK_PRINTER_TYPES, 3001, "AP_TYPE1"),
    (SlotBlock.APPLETALK_BINARY_PROTOCOL, 3101, "AP_PCOMM1"),
)

_PRINTER_LINES = (
    (PrinterField.PORT, 100, 240, "PROUT"),
    (PrinterField.PRE_STRING, 101, 241, "PREST"),
    (PrinterField.POST_STRING, 102, 242, "POSTR"),
    (PrinterField.CONVERT_LF, 103, 243, "CHGLF"),
    (PrinterField.NAME, 104, 244, "NAME"),
)

_MAIL_LINES = (
    (MailField.SERVER, 4100, "MAIL_IP"),
    (MailField.ACCOUNT, 4101, "MAIL_ACC"),
    (MailField.PASSWORD, 4102, "MAIL_PAS"),
    (MailField.CHECK_INTERVAL, 4103, "MAIL_INT"),
    (MailField.BANNER, 4104, "MAIL_BAN"),
    (MailField.REDIRECT_ACCOUNT, 4105, "MAIL_RED"),
    (MailField.PORT, 4106, "MAIL_POR"),
    (MailField.PRINT_EVERY_MAIL, 4107, "MAIL_EVR"),
    (MailField.NOTIFY, 4108, "MAIL_NOT"),
    (MailField.PRINTER_MODEL, 4109, "MAIL_MOD"),
)

_MANAGER_LINES = (
    (ManagerField.ADDRESS, 6011, 6041, "IP"),
    (ManagerField.ACCESS, 6012, 6042, "ACCP"),
    (ManagerField.COMMUNITY, 6013, 6043, "CSTR"),
)

_TRAP_LINES = (
    (TrapField.ADDRESS, 6111, 6141, "IP"),
    (TrapField.SEVERITY, 6112, 6142, "S"),
    (TrapField.COMMUNITY, 6113, 6143, "CSTR"),
    (TrapField.ENABLED, 6114, 6144, "ENAB"),
)


def test_every_parameter_line_keeps_its_name_and_number() -> None:
    assert [(member.name, member.value) for member in ParameterLine] == [
        (name, line) for name, line, _ in _PARAMETER_LINES
    ]


@pytest.mark.parametrize(("name", "line", "token"), _PARAMETER_LINES)
def test_parameter_line_names_its_token(name: str, line: int, token: str) -> None:
    assert cat.TOKENS[ParameterLine[name]] == token
    assert cat.known(line)


@pytest.mark.parametrize(("block", "first", "token"), _SLOT_BLOCKS)
def test_slot_block_puts_slot_one_on_its_line(block: SlotBlock, first: int, token: str) -> None:
    assert cat.slot_line(block, 1) == first
    assert cat.TOKENS[first] == token


@pytest.mark.parametrize(("field", "first", "last", "suffix"), _PRINTER_LINES)
def test_printer_field_resolves_to_its_line_for_the_first_and_last_printer(
    field: PrinterField, first: int, last: int, suffix: str
) -> None:
    assert (cat.printer_line(1, field), cat.printer_line(8, field)) == (first, last)
    assert (cat.TOKENS[first], cat.TOKENS[last]) == (f"L1_{suffix}", f"L8_{suffix}")


@pytest.mark.parametrize(("field", "line", "token"), _MAIL_LINES)
def test_mail_field_resolves_to_its_line(field: MailField, line: int, token: str) -> None:
    assert cat.mail_line(field) == line
    assert cat.TOKENS[line] == token


@pytest.mark.parametrize(("field", "first", "last", "suffix"), _MANAGER_LINES)
def test_manager_field_resolves_to_its_line_for_the_first_and_last_slot(
    field: ManagerField, first: int, last: int, suffix: str
) -> None:
    assert (cat.manager_line(1, field), cat.manager_line(4, field)) == (first, last)
    assert (cat.TOKENS[first], cat.TOKENS[last]) == (f"M1_{suffix}", f"M4_{suffix}")


@pytest.mark.parametrize(("field", "first", "last", "suffix"), _TRAP_LINES)
def test_trap_field_resolves_to_its_line_for_the_first_and_last_slot(
    field: TrapField, first: int, last: int, suffix: str
) -> None:
    assert (cat.trap_line(1, field), cat.trap_line(4, field)) == (first, last)
    assert (cat.TOKENS[first], cat.TOKENS[last]) == (f"T1_{suffix}", f"T4_{suffix}")


@pytest.mark.parametrize(
    ("enum", "table"),
    [
        (PrinterField, _PRINTER_LINES),
        (MailField, _MAIL_LINES),
        (ManagerField, _MANAGER_LINES),
        (TrapField, _TRAP_LINES),
        (SlotBlock, _SLOT_BLOCKS),
    ],
)
def test_every_member_is_pinned(enum: type[IntEnum], table: tuple[tuple[object, ...], ...]) -> None:
    assert [row[0] for row in table] == list(enum)
