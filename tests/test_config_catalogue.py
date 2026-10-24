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
    PrinterField,
    TrapField,
)

if TYPE_CHECKING:
    from enum import IntEnum

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
    ],
)
def test_every_member_is_pinned(enum: type[IntEnum], table: tuple[tuple[object, ...], ...]) -> None:
    assert [row[0] for row in table] == list(enum)
