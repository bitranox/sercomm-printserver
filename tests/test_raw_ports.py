"""The two RAW port rows: which port each logical printer has in each, and which firmware opens which."""

from __future__ import annotations

import pytest

from sercomm_printserver.domain.raw_ports import (
    DSI_RAW_PORTS,
    RawPortRow,
    raw_port_of,
    raw_port_rows,
    raw_printer_at,
)


@pytest.mark.parametrize(
    ("row", "expected"),
    [(RawPortRow.BASE, (9100, 9101, 9102)), (RawPortRow.DSI, (4010, 4020, 4030))],
)
def test_each_row_gives_the_logical_printers_1_to_3_their_ports(row: RawPortRow, expected: tuple[int, ...]) -> None:
    assert tuple(raw_port_of(number, row, raw_port_base=9100) for number in (1, 2, 3)) == expected


def test_the_dsi_row_ignores_raw_port_base() -> None:
    assert raw_port_of(2, RawPortRow.DSI, raw_port_base=5000) == DSI_RAW_PORTS[1]


@pytest.mark.parametrize("number", [0, 4, 8, -1])
@pytest.mark.parametrize("row", list(RawPortRow))
def test_only_the_logical_printers_1_to_3_have_a_raw_port(number: int, row: RawPortRow) -> None:
    with pytest.raises(ValueError, match="no RAW port"):
        raw_port_of(number, row, raw_port_base=9100)


def test_a_base_row_past_the_last_tcp_port_is_refused() -> None:
    with pytest.raises(ValueError, match="no RAW port"):
        raw_port_of(3, RawPortRow.BASE, raw_port_base=65534)


@pytest.mark.parametrize(
    ("port", "expected"),
    [
        (9100, (1, RawPortRow.BASE)),
        (9102, (3, RawPortRow.BASE)),
        (4010, (1, RawPortRow.DSI)),
        (4020, (2, RawPortRow.DSI)),
        (4030, (3, RawPortRow.DSI)),
    ],
)
def test_a_raw_port_names_its_logical_printer_and_row(port: int, expected: tuple[int, RawPortRow]) -> None:
    found = raw_printer_at(port, raw_port_base=9100)
    assert found is not None
    assert (found.logical_printer, found.row) == expected


@pytest.mark.parametrize("port", [9099, 9103, 4000, 4011, 4040, 515, 0])
def test_a_port_in_neither_row_names_no_printer(port: int) -> None:
    assert raw_printer_at(port, raw_port_base=9100) is None


def test_a_base_row_overlapping_the_dsi_row_is_read_as_the_base_row() -> None:
    found = raw_printer_at(4020, raw_port_base=4019)
    assert found is not None
    assert (found.logical_printer, found.row) == (2, RawPortRow.BASE)


@pytest.mark.parametrize(
    ("firmware", "expected"),
    [
        ("6022", frozenset({RawPortRow.BASE, RawPortRow.DSI})),
        ("6A10", frozenset({RawPortRow.DSI})),
        ("6a10", frozenset({RawPortRow.DSI})),
        (" 6022 ", frozenset({RawPortRow.BASE, RawPortRow.DSI})),
    ],
)
def test_the_measured_firmwares_name_the_rows_they_open(firmware: str, expected: frozenset[RawPortRow]) -> None:
    assert raw_port_rows(firmware) == expected


@pytest.mark.parametrize("firmware", ["6034", "6017", "", "unknown"])
def test_an_unmeasured_firmware_names_no_rows(firmware: str) -> None:
    assert raw_port_rows(firmware) is None
