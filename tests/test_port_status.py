"""The Telnet ``monitor`` parser: typed port names, and the refusals it makes in a fixed order."""

from __future__ import annotations

import json

import pytest

from sercomm_printserver.domain.config_types import PortId
from sercomm_printserver.domain.errors import DeviceResponseError
from sercomm_printserver.domain.port_status import PortState, PortStatus, PortType, PrinterStatus, parse_monitor

_IDLE_P1 = "(P1)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n"


def _block(port: str = "P1", *, state: str = "Idle", extra: str = "") -> str:
    return f"({port})STATE: {state}\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n{extra}"


@pytest.mark.parametrize("port", list(PortId))
def test_every_port_the_firmware_prints_parses_into_its_port_id(port: PortId) -> None:
    (status,) = parse_monitor(_block(port.value))

    assert status.port is port


def test_a_port_name_the_firmware_never_prints_is_refused_as_a_device_response() -> None:
    with pytest.raises(DeviceResponseError, match=r"^port P9: port name is 'P9', which this firmware family does not"):
        parse_monitor(_block("P9"))


def test_an_unknown_port_with_another_defect_reports_the_other_defect() -> None:
    with pytest.raises(DeviceResponseError, match=r"^port P9: STATE is 'Zz', which"):
        parse_monitor(_block("P9", state="Zz"))
    with pytest.raises(DeviceResponseError, match=r"^port LPT1: unexpected monitor line\(s\) TONER$"):
        parse_monitor(_block("LPT1", extra="TONER: low\r\n"))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "monitor output holds no port status"),
        ("(P1)STATE: Idle\r\n", "port P1: monitor output has no TYPE line"),
        ("(P1)STATE: Idle\r\nTYPE: Parallel\r\n", "port P1: monitor output has no PRINTER STATUS line"),
        (_block(state=""), "port P1: STATE is '', which this firmware family does not print"),
        (
            "(P1)STATE: Idle\r\nTYPE: Firewire\r\nPRINTER STATUS: Offline\r\n",
            "port P1: TYPE is 'Firewire', which this firmware family does not print",
        ),
        (_IDLE_P1 + "ZED: 1\r\nTONER: low\r\n", "port P1: unexpected monitor line(s) TONER, ZED"),
        (_IDLE_P1 + "state: Idle\r\n", "port P1: unexpected monitor line(s) state"),
        (_IDLE_P1 + "port: P2\r\n", "port P1: unexpected monitor line(s) port"),
        (_IDLE_P1 + "garbage\r\n", "port P1: unexpected monitor line(s) garbage"),
        (_IDLE_P1 + "BYTES SERVICED: x\r\nTONER: low\r\n", "port P1: unexpected monitor line(s) TONER"),
        (_block(state="Zz", extra="BYTES SERVICED: x\r\n"), "port P1: BYTES SERVICED is 'x', expected a number"),
        ("(P1)STATE: Zz\r\nPRINTER STATUS: Offline\r\n", "port P1: STATE is 'Zz', which this firmware family"),
        (
            "(P1)STATE: Idle\r\nTYPE: X\r\nPRINTER STATUS: Y\r\n",
            "port P1: TYPE is 'X', which this firmware family does not print",
        ),
        (
            _IDLE_P1 + "\r\n(P2)STATE: Idle\r\nTYPE: Nope\r\nPRINTER STATUS: Offline\r\n",
            "port P2: TYPE is 'Nope', which",
        ),
    ],
)
def test_each_defect_is_refused_with_the_message_it_has_always_had(text: str, message: str) -> None:
    with pytest.raises(DeviceResponseError) as caught:
        parse_monitor(text)

    assert type(caught.value) is DeviceResponseError
    assert str(caught.value).startswith(message)


@pytest.mark.parametrize("count", ["-1", "+5", "1_000", " ", "", chr(0x0662), chr(0x00B2), "0x10"])
def test_a_byte_count_that_is_not_plain_ascii_digits_is_refused(count: str) -> None:
    with pytest.raises(DeviceResponseError) as caught:
        parse_monitor(_IDLE_P1 + f"BYTES SERVICED: {count}\r\n")

    assert str(caught.value) == f"port P1: BYTES SERVICED is {count.strip()!r}, expected a number"


def test_a_busy_port_reads_its_count_and_holder() -> None:
    (status,) = parse_monitor(
        "(P1)STATE: Printing\r\nTYPE: Parallel\r\nPRINTER STATUS: On-Line\r\n"
        "BYTES SERVICED:          42\r\nOCCUPIED BY: Direct Socket\r\n"
    )

    assert status == PortStatus(
        port=PortId.P1,
        state=PortState.PRINTING,
        type=PortType.PARALLEL,
        printer_status=PrinterStatus.ON_LINE,
        bytes_serviced=42,
        occupied_by="Direct Socket",
    )


def test_a_repeated_line_keeps_the_last_value() -> None:
    (status,) = parse_monitor("(P1)STATE: Idle\r\nTYPE: Firewire\r\nTYPE: Serial\r\nPRINTER STATUS: Offline\r\n")

    assert status.type is PortType.SERIAL


def test_lines_after_a_blank_line_and_before_the_first_block_are_ignored() -> None:
    ports = parse_monitor("monitor\r\nfoo: bar\r\n" + _IDLE_P1 + "\r\nTONER: low\r\n")

    assert [port.port for port in ports] == [PortId.P1]


def test_validation_by_field_name_takes_plain_strings() -> None:
    status = PortStatus.model_validate({"port": "SP", "state": "Idle", "type": "Serial", "printer_status": "Offline"})

    assert (status.port, status.state, status.type) == (PortId.SP, PortState.IDLE, PortType.SERIAL)


def test_the_json_export_keeps_the_field_names_and_plain_values() -> None:
    (status,) = parse_monitor(_IDLE_P1)

    assert json.loads(status.model_dump_json()) == {
        "port": "P1",
        "state": "Idle",
        "type": "Parallel",
        "printer_status": "Offline",
        "bytes_serviced": None,
        "occupied_by": None,
    }
