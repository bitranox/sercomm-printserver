"""PSINF, SYST and Telnet monitor parsing, against the real (scrubbed) device output."""

from __future__ import annotations

from ipaddress import IPv4Address
from pathlib import Path

import pytest

from sercomm_printserver.domain.device_info import mac_from_default_name, parse_firmware_reply, parse_psinf
from sercomm_printserver.domain.errors import DeviceResponseError
from sercomm_printserver.domain.port_status import PortState, PortType, PrinterStatus, parse_monitor

_DUMPS = Path(__file__).resolve().parents[1] / "docs" / "device-dump"

#: The PS301's monitor output exactly as the Telnet session delivered it while idle.
_IDLE_MONITOR = (
    "monitor\r\n\r\n"
    "(P1)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n\r\n"
    "(P2)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n\r\n"
    "(SP)STATE: Idle\r\nTYPE: Serial\r\nPRINTER STATUS: Offline\r\n\r\n"
)


def test_psinf_lifts_identity_and_address_and_keeps_every_section() -> None:
    info = parse_psinf((_DUMPS / "PSINF.txt").read_text(encoding="ascii"))

    assert (info.hardware_id, info.firmware_version, info.protocol_id) == ("024010XXXX", "6022", "003F")
    assert (info.default_name, info.server_name) == ("SC123456", "PS_EXAMPLE")
    assert info.mac_address == "00:c0:02:12:34:56"
    assert (info.ip_address, info.subnet_mask) == (IPv4Address("192.0.2.52"), IPv4Address("255.255.255.0"))
    assert [section.title for section in info.sections] == ["Netware Info", "AppleTalk Info", "TCP/IP Info", "SMB Info"]
    appletalk = next(section for section in info.sections if section.title == "AppleTalk Info")
    assert [entry.key for entry in appletalk.entries] == [
        "Printer Type",
        "PS_EXAMPLE",
        "PS_EXAMPLE_P2",
        "PS_EXAMPLE_SP",
    ]


def test_psinf_as_the_device_sends_it_with_crlf_and_form_feed_parses_the_same() -> None:
    text = (_DUMPS / "PSINF.txt").read_text(encoding="ascii")
    wire = text.replace("\n", "\r\n") + "\x0c\r"

    assert parse_psinf(wire) == parse_psinf(text)


def test_psinf_without_an_address_reports_none_rather_than_failing() -> None:
    text = (_DUMPS / "PSINF.txt").read_text(encoding="ascii").replace("IP Address: 192.0.2.52", "IP Address: N/A")

    assert parse_psinf(text).ip_address is None


def test_psinf_missing_a_header_line_is_refused() -> None:
    text = (_DUMPS / "PSINF.txt").read_text(encoding="ascii").replace("Firmware Version: 6022\n", "")

    with pytest.raises(DeviceResponseError, match="no 'Firmware Version' line"):
        parse_psinf(text)


def test_psinf_with_a_line_that_is_not_key_value_is_refused() -> None:
    with pytest.raises(DeviceResponseError, match="not 'Key: Value'"):
        parse_psinf("Hardware ID: 1\ngarbage line\n")


@pytest.mark.parametrize(
    ("name", "mac"),
    [("SC123456", "00:c0:02:12:34:56"), ("scabcdef", "00:c0:02:ab:cd:ef"), ("PS123456", None), ("SC12345", None)],
)
def test_the_mac_address_follows_from_the_default_name(name: str, mac: str | None) -> None:
    assert mac_from_default_name(name) == mac


def test_the_firmware_version_comes_from_the_syst_reply() -> None:
    assert parse_firmware_reply("215 Print Server FW 6022\r\n") == "6022"


def test_a_syst_reply_from_another_server_is_refused() -> None:
    with pytest.raises(DeviceResponseError, match="unexpected SYST reply"):
        parse_firmware_reply("215 UNIX Type: L8")


def test_idle_monitor_output_reads_as_three_idle_ports() -> None:
    ports = parse_monitor(_IDLE_MONITOR)

    assert [(port.port, port.type) for port in ports] == [
        ("P1", PortType.PARALLEL),
        ("P2", PortType.PARALLEL),
        ("SP", PortType.SERIAL),
    ]
    assert all(port.state is PortState.IDLE and port.printer_status is PrinterStatus.OFFLINE for port in ports)
    assert all(port.bytes_serviced is None and port.occupied_by is None for port in ports)


def test_a_busy_port_reports_bytes_and_who_holds_it() -> None:
    text = (_DUMPS / "telnet-monitor.txt").read_text(encoding="ascii")

    ports = parse_monitor(text)

    assert ports[0].state is PortState.PRINTING
    assert (ports[0].bytes_serviced, ports[0].occupied_by) == (0, "Direct Socket")
    assert ports[2].printer_status is PrinterStatus.ON_LINE


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("PS>", "holds no port status"),
        ("(P1)STATE: Idle\r\nPRINTER STATUS: Offline\r\n", "no TYPE line"),
        ("(P1)STATE: Sleeping\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n", "STATE is 'Sleeping'"),
        ("(P1)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Paper Jam\r\n", "PRINTER STATUS is 'Paper Jam'"),
        ("(P1)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\nTONER: low\r\n", "unexpected monitor line"),
        (
            "(P1)STATE: Printing\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\nBYTES SERVICED: -1\r\n",
            "expected a number",
        ),
    ],
)
def test_monitor_output_this_firmware_family_never_prints_is_refused(text: str, message: str) -> None:
    with pytest.raises(DeviceResponseError, match=message):
        parse_monitor(text)
