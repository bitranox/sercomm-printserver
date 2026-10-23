"""CONFIG text <-> DeviceConfig: round trip, model shapes, refusals.

The real fixture is ``docs/device-dump/CONFIG.txt``, a PS301 (2 parallel + 1 serial) dump with
its addresses and names replaced; its line structure is byte-identical to what the device sends.
The 1-port fixture is built from the parameter set the PPSX1 firmware declares
(``docs/config-keys.md``, column A) with the manual's factory defaults.
"""

from __future__ import annotations

from ipaddress import IPv4Address
from pathlib import Path

import pytest

from sercomm_printserver.domain.config_codec import (
    diff_config,
    find_line,
    parse_config,
    render_config,
    with_value,
)
from sercomm_printserver.domain.config_lines import ConfigLine
from sercomm_printserver.domain.config_model import LogicalPrinter
from sercomm_printserver.domain.config_types import BaudRate, Handshake, LptMode, Parity, PortId
from sercomm_printserver.domain.errors import ConfigFormatError

_DUMP = Path(__file__).resolve().parents[1] / "docs" / "device-dump" / "CONFIG.txt"

_ONE_PORT_LINES = (
    "0001 BOX_NAME:SC123456",
    "0011 IPXSPX_P:Enable",
    "0012 TCPIP_P :Enable",
    "0013 APTALK_P:Enable",
    "0014 NETB_P:Enable",
    "0100 L1_PROUT:P1",
    "0101 L1_PREST:",
    "0102 L1_POSTR:",
    "0103 L1_CHGLF:No",
    "0120 L2_PROUT:P1",
    "0121 L2_PREST:1B45",
    "0122 L2_POSTR:0C",
    "0123 L2_CHGLF:Yes",
    "0140 L3_PROUT:P1",
    "0141 L3_PREST:",
    "0142 L3_POSTR:",
    "0143 L3_CHGLF:No",
    "0501 LPT1MODE:Busy",
    "2000 NOP_MODE:PS",
    "2001 NFREthII:Enable",
    "2002 NFR802.2:Enable",
    "2003 NFR802.3:Enable",
    "2004 NFRSNAP :Enable",
    "2101 NFS_NAME:",
    "2102 N_NOTIFY:No",
    "2103 N_FREQ  :1",
    "2110 NDS_TREE:",
    "2111 NCONTEXT:",
    "2501 NR_NAME1:",
    "3000 AP_ZONE:*",
    "3001 AP_TYPE1:LaserWriter",
    "3101 AP_PCOMM1:Yes",
    "4000 IP_ADDR:0.0.0.0",
    "4001 GATEWAY:0.0.0.0",
    "4002 MASK   :0.0.0.0",
    "4010 TCP_INT:2",
    "4011 TCP_CNT:254",
    "4012 WINS_IP:0.0.0.0",
    "4020 DHCP_MODE:Enable",
    "5000 SMBGNAME:workgroup",
    "5001 SMBDROP:No",
    "5002 SMBDELAY:0",
    "6000 CONTACT:",
    "6001 LOCATION:",
    "6011 M1_IP:0.0.0.0",
    "6012 M1_ACCP:Not Accessible",
    "6013 M1_CSTR:public",
    "6111 T1_IP:0.0.0.0",
    "6112 T1_S:0",
    "6113 T1_CSTR:public",
    "6114 T1_ENAB:Disable",
)
_ONE_PORT = "".join(f"{line}\n" for line in _ONE_PORT_LINES)


@pytest.fixture
def dump_text() -> str:
    return _DUMP.read_text(encoding="ascii")


# ---------------------------------------------------------------- round trip and shapes


def test_the_device_dump_renders_back_byte_for_byte(dump_text: str) -> None:
    assert render_config(parse_config(dump_text)) == dump_text


def test_the_two_parallel_one_serial_dump_reads_as_its_typed_settings(dump_text: str) -> None:
    config = parse_config(dump_text)

    assert config.box_name == "PS_EXAMPLE"
    assert config.tcp_ip.ip_address == IPv4Address("192.0.2.52")
    assert config.tcp_ip.dhcp is False
    assert config.serial is not None
    assert (config.serial.baud_rate, config.serial.parity, config.serial.handshake) == (
        BaudRate.B9600,
        Parity.NONE,
        Handshake.BOTH,
    )
    assert [printer.port for printer in config.logical_printers] == [
        PortId.P1,
        PortId.P2,
        PortId.SP,
        PortId.P1,
        PortId.P2,
        PortId.SP,
        PortId.P1,
        PortId.P2,
    ]
    assert [(mode.slot, mode.mode) for mode in config.parallel_modes] == [
        (1, LptMode.BUSY),
        (2, LptMode.BUSY),
        (4, LptMode.BUSY),
    ]
    assert config.mail is not None
    assert config.mail.password == "**********"
    assert config.unmodeled == ()


def test_a_one_port_model_has_three_printers_and_no_serial_port() -> None:
    config = parse_config(_ONE_PORT)

    assert [printer.number for printer in config.logical_printers] == [1, 2, 3]
    assert config.serial is None
    assert config.mail is None
    assert config.logical_printers[1].pre_string == "1B45"
    assert config.logical_printers[1].convert_lf is True
    assert render_config(config) == _ONE_PORT


def test_a_parameter_the_model_does_not_know_is_kept_at_its_line() -> None:
    text = _ONE_PORT.replace("0501 LPT1MODE:Busy\n", "0501 LPT1MODE:Busy\n0521 P1_STROBE:Short\n")
    text += "7000 SSID:my wlan\n"

    config = parse_config(text)

    assert [(line.number, line.token, line.value) for line in config.unmodeled] == [
        (521, "P1_STROBE", "Short"),
        (7000, "SSID", "my wlan"),
    ]
    assert render_config(config) == text


# ---------------------------------------------------------------- the line format


def test_lines_not_starting_with_a_digit_are_comments_and_crlf_is_accepted() -> None:
    text = "# exported by hand\r\n" + _ONE_PORT.replace("\n", "\r\n")

    assert render_config(parse_config(text)) == _ONE_PORT


def test_values_are_read_without_surrounding_spaces_and_spelling_is_normalised() -> None:
    text = _ONE_PORT.replace("0103 L1_CHGLF:No", "0103 L1_CHGLF: no").replace("2000 NOP_MODE:PS", "2000 NOP_MODE:ps")

    rendered = render_config(parse_config(text))

    assert "0103 L1_CHGLF:No\n" in rendered
    assert "2000 NOP_MODE:PS\n" in rendered


def test_a_line_number_given_twice_is_refused() -> None:
    with pytest.raises(ConfigFormatError, match="0001 appears twice"):
        parse_config(_ONE_PORT + "0001 BOX_NAME:OTHER\n")


def test_a_line_without_a_colon_is_refused() -> None:
    with pytest.raises(ConfigFormatError, match="expected 'NNNN TOKEN:VALUE'"):
        parse_config(_ONE_PORT + "6001 LOCATION\n")


def test_a_missing_required_parameter_is_named() -> None:
    text = _ONE_PORT.replace("4002 MASK   :0.0.0.0\n", "")

    with pytest.raises(ConfigFormatError, match=r"parameter 4002 \(MASK\) is missing"):
        parse_config(text)


# ---------------------------------------------------------------- changing a value


def test_a_value_set_by_token_shows_up_in_the_diff_and_nowhere_else(dump_text: str) -> None:
    before = parse_config(dump_text)

    after = with_value(before, "ip_addr", "192.0.2.99")

    changes = diff_config(before, after)
    assert [(change.number, change.token, change.old, change.new) for change in changes] == [
        (4000, "IP_ADDR", "192.0.2.52", "192.0.2.99")
    ]


def test_a_parameter_can_be_named_by_its_line_number(dump_text: str) -> None:
    assert find_line(parse_config(dump_text), "4020").token == "DHCP_MODE"


def test_an_unknown_parameter_name_is_refused(dump_text: str) -> None:
    with pytest.raises(ConfigFormatError, match="no parameter 'NOPE'"):
        with_value(parse_config(dump_text), "NOPE", "x")


def test_a_lowercase_choice_is_stored_in_the_firmware_spelling(dump_text: str) -> None:
    after = with_value(parse_config(dump_text), "PARITY", "odd")

    assert find_line(after, "PARITY").value == "ODD"


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("IP_ADDR", "300.1.1.1", "expected an IPv4 address"),
        ("IP_ADDR", "", "expected an IPv4 address"),
        ("BAUDRATE", "1234", "expected one of 300, 600"),
        ("BAUDRATE", "fast", "expected a whole number"),
        ("TCP_INT", "\u0662", "expected a whole number"),
        ("TCP_INT", "256", "less than or equal to 255"),
        ("PARITY", "Mark", "expected one of None, ODD, EVEN"),
        ("DHCP_MODE", "on", "expected Enable or Disable"),
        ("L1_CHGLF", "true", "expected Yes or No"),
        ("T1_S", "3", "less than or equal to 2"),
        ("BOX_NAME", "has space", "without spaces"),
        ("BOX_NAME", "A" * 20, "without spaces"),
        ("L1_PREST", "1B3", "pairs of hex digits"),
        ("L1_PREST", "ZZ", "pairs of hex digits"),
        ("L1_PREST", "00" * 16, "pairs of hex digits"),
        ("CONTACT", "x" * 32, "at most 31 printable ASCII characters"),
        ("CONTACT", "M\u00fcller", "at most 31 printable ASCII characters"),
        ("CONTACT", "\U0001f5a8 printer", "at most 31 printable ASCII characters"),
        ("CONTACT", "\u5370\u5237\u673a", "at most 31 printable ASCII characters"),
        ("CONTACT", "a\x00b", "at most 31 printable ASCII characters"),
    ],
)
def test_an_invalid_value_is_refused_with_a_reason(dump_text: str, key: str, value: str, message: str) -> None:
    with pytest.raises(ConfigFormatError, match=message):
        with_value(parse_config(dump_text), key, value)


def test_a_value_cannot_smuggle_in_a_second_parameter(dump_text: str) -> None:
    with pytest.raises(ConfigFormatError, match="at most 31 printable ASCII characters"):
        with_value(parse_config(dump_text), "CONTACT", "x\n4000 IP_ADDR:192.0.2.66")


def test_the_empty_box_name_is_refused(dump_text: str) -> None:
    with pytest.raises(ConfigFormatError, match="must be 1 to 19"):
        with_value(parse_config(dump_text), "BOX_NAME", "")


def test_a_logical_printer_the_family_has_no_line_for_cannot_be_rendered(dump_text: str) -> None:
    config = parse_config(dump_text)
    ninth = LogicalPrinter(number=9, port=PortId.P1, pre_string="", post_string="", convert_lf=False)
    widened = config.model_copy(update={"logical_printers": (*config.logical_printers, ninth)})

    with pytest.raises(ConfigFormatError, match="parameter 0260 does not exist"):
        render_config(widened)


def test_a_config_line_renders_with_its_token_padding() -> None:
    assert ConfigLine(number=4002, token="MASK   ", value="255.255.255.0").render() == "4002 MASK   :255.255.255.0"


# ---------------------------------------------------------------- firmware 6A10 (a second real PS301)


def test_firmware_6a10_without_wins_and_dhcp_lines_round_trips() -> None:
    text = (_DUMP.parent / "fw6a10" / "CONFIG.txt").read_text(encoding="ascii")

    config = parse_config(text)

    assert (config.tcp_ip.wins_server, config.tcp_ip.dhcp) == (None, None)
    assert [mode.slot for mode in config.parallel_modes] == [1]
    assert config.serial is not None
    assert config.serial.handshake is Handshake.HARDWARE
    assert render_config(config) == text
