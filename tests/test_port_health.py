"""Which port readings count as a wedge candidate, and the verdicts derived from them."""

from __future__ import annotations

import pytest

from sercomm_printserver.domain.port_health import PortVerdict, is_wedge_candidate, probed_verdict, unprobed_verdict
from sercomm_printserver.domain.port_status import Occupant, PortStatus, parse_monitor

pytestmark = pytest.mark.os_agnostic


def _serial(state: str, *, occupied_by: str | None = None, serviced: int | None = None) -> PortStatus:
    block = f"(SP)STATE: {state}\r\nTYPE: Serial\r\nPRINTER STATUS: On-Line\r\n"
    if serviced is not None:
        block += f"BYTES SERVICED: {serviced:>10}\r\n"
    if occupied_by is not None:
        block += f"OCCUPIED BY: {occupied_by}\r\n"
    [port] = parse_monitor(block)
    return port


@pytest.mark.parametrize(
    ("status", "candidate"),
    [
        (_serial("Printing", occupied_by="Direct Socket", serviced=0), True),
        (_serial("Printing", occupied_by="LPD", serviced=0), False),
        (_serial("Printing", occupied_by="192.0.2.7", serviced=0), False),
        (_serial("Printing", occupied_by="Direct Socket", serviced=1), False),
        (_serial("Idle"), False),
    ],
    ids=["direct-socket-0-bytes", "lpd", "unlisted-holder", "bytes-moved", "idle"],
)
def test_only_printing_direct_socket_with_nothing_serviced_is_a_candidate(status: PortStatus, candidate: bool) -> None:
    assert is_wedge_candidate(status) is candidate


def test_the_occupant_names_the_known_protocols_and_nothing_else() -> None:
    assert _serial("Printing", occupied_by="Direct Socket", serviced=0).occupant is Occupant.DIRECT_SOCKET
    assert _serial("Printing", occupied_by="LPD", serviced=0).occupant is Occupant.LPD
    assert _serial("Printing", occupied_by="192.0.2.7", serviced=0).occupant is None
    assert _serial("Idle").occupant is None


def test_a_candidate_without_probes_is_unprobed_and_a_plain_busy_port_is_printing() -> None:
    assert unprobed_verdict(_serial("Printing", occupied_by="Direct Socket", serviced=0)) is PortVerdict.UNPROBED
    assert unprobed_verdict(_serial("Printing", occupied_by="LPD", serviced=0)) is PortVerdict.PRINTING
    assert unprobed_verdict(_serial("Idle")) is PortVerdict.IDLE


@pytest.mark.parametrize(
    ("accepted", "verdict"),
    [((True, True), PortVerdict.WEDGED), ((True, False), PortVerdict.HELD), ((), PortVerdict.UNPROBED)],
)
def test_a_candidate_is_wedged_only_when_every_probe_got_in(accepted: tuple[bool, ...], verdict: PortVerdict) -> None:
    assert probed_verdict(accepted=accepted) is verdict
