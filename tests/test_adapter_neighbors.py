"""The ipscout neighbour-table adapter, against the real ipscout and this host's real kernel.

Only the paths that change nothing run here: refusals happen before anything is written, and an
unprivileged process is refused by the kernel itself. A privileged process would really write the
table, so the refusal test skips under root rather than mutate the host.
"""

from __future__ import annotations

import os
import sys
from ipaddress import IPv4Address
from typing import TYPE_CHECKING

import ipscout
import pytest

from sercomm_printserver.adapters.neighbors import IpscoutNeighborTable
from sercomm_printserver.domain.device_info import normalise_mac
from sercomm_printserver.domain.errors import HostPrivilegeError, NeighborTableError
from sercomm_printserver.domain.neighbor import AddressHolder, LookupMethod

if TYPE_CHECKING:
    from collections.abc import Callable

    from sercomm_printserver.application.ports import NeighborTable

_MAC = normalise_mac("00:00:5e:00:53:07")
_IP = IPv4Address("192.0.2.77")


def test_the_adapter_satisfies_the_port() -> None:
    table: NeighborTable = IpscoutNeighborTable()
    assert isinstance(table, IpscoutNeighborTable)


@pytest.mark.os_agnostic
def test_a_broadcast_mac_is_refused_before_anything_is_written() -> None:
    with pytest.raises(ValueError, match="broadcast or multicast"):
        IpscoutNeighborTable().set_static(_IP, normalise_mac("ff:ff:ff:ff:ff:ff"))


@pytest.mark.os_agnostic
def test_an_address_in_no_local_subnet_without_an_interface_is_a_value_error() -> None:
    # 192.0.2.0/24 is documentation space no test host holds, so no interface's subnet has it;
    # the refusal comes before any write and needs no privilege.
    with pytest.raises(ValueError, match="no interface on this host has a subnet holding"):
        IpscoutNeighborTable().set_static(_IP, _MAC)


@pytest.mark.os_linux
@pytest.mark.skipif(sys.platform != "linux", reason="the unprivileged netlink refusal is Linux behaviour")
def test_an_unprivileged_write_becomes_a_host_privilege_error() -> None:
    # The skipif above already skips this off Linux; pyright checks each platform separately and
    # only narrows os.geteuid away on Windows through a statement it can read.
    if sys.platform == "win32":
        return
    if os.geteuid() == 0:
        pytest.skip("running as root would really write this host's neighbour table")
    route = ipscout.default_gateway()
    if route is None or route.interface is None:
        pytest.skip("no default route to borrow an interface from")

    with pytest.raises(HostPrivilegeError, match="changing the neighbour table needs root or CAP_NET_ADMIN"):
        IpscoutNeighborTable(interface=route.interface).set_static(_IP, _MAC)


@pytest.mark.os_linux
@pytest.mark.skipif(sys.platform != "linux", reason="measured on Linux: an off-link address resolves to the router")
def test_an_address_off_this_hosts_network_is_a_value_error() -> None:
    # 192.0.2.0/24 is documentation space no test host holds, so ipscout reaches it through the
    # default route and answers for the router; borrowing it would map the router's address.
    if ipscout.default_gateway() is None:
        pytest.skip("no default route: the address has no route at all")

    with pytest.raises(ValueError, match=r"192\.0\.2\.254 is not on this host's network; it is reached through"):
        IpscoutNeighborTable().holder_of(IPv4Address("192.0.2.254"))


# ipscout's reply is the third-party edge the adapter translates; the tests below substitute
# that reply, since no host can be made to hold a chosen MAC, or to lack the right to send an
# ARP request, without changing the host.


def _replying(reply: ipscout.MacLookup) -> Callable[..., ipscout.MacLookup]:
    """Return a stand-in for ``ipscout.lookup_mac`` that records its call and answers ``reply``."""

    def lookup_mac(ip: str, *, active: bool = False, fallback_to_cache: bool = False) -> ipscout.MacLookup:
        assert (ip, active, fallback_to_cache) == (str(_IP), True, True), "ask actively, the cache only when it cannot"
        return reply

    return lookup_mac


def _found(mac: str | None, method: ipscout.MacMethod) -> ipscout.MacLookup:
    scope = ipscout.MacScope.UNKNOWN if mac is None else ipscout.MacScope.DIRECT
    return ipscout.MacLookup(ip=str(_IP), mac=mac, scope=scope, method=method)


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("mac", "method", "expected"),
    [
        ("00:00:5e:00:53:07", ipscout.MacMethod.ACTIVE, AddressHolder(mac=_MAC, method=LookupMethod.ACTIVE)),
        ("00:00:5e:00:53:07", ipscout.MacMethod.CACHE, AddressHolder(mac=_MAC, method=LookupMethod.CACHE)),
        (None, ipscout.MacMethod.ACTIVE, AddressHolder(mac=None, method=LookupMethod.ACTIVE)),
        (None, ipscout.MacMethod.CACHE, AddressHolder(mac=None, method=LookupMethod.CACHE)),
    ],
    ids=["held-asked", "held-cached", "free-asked", "unknown-cached"],
)
def test_holder_of_reports_the_mac_and_how_it_was_found(
    monkeypatch: pytest.MonkeyPatch, mac: str | None, method: ipscout.MacMethod, expected: AddressHolder
) -> None:
    monkeypatch.setattr(ipscout, "lookup_mac", _replying(_found(mac, method)))

    assert IpscoutNeighborTable().holder_of(_IP) == expected


@pytest.mark.os_agnostic
def test_holder_of_normalises_the_spelling_ipscout_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    # model_construct: ipscout's own record would normalise the spelling first, but the adapter
    # must not depend on that to compare MACs as they are.
    reply = ipscout.MacLookup.model_construct(
        ip=str(_IP),
        mac="00-00-5E-00-53-07",
        scope=ipscout.MacScope.DIRECT,
        via_ip=None,
        interface=None,
        method=ipscout.MacMethod.ACTIVE,
    )
    monkeypatch.setattr(ipscout, "lookup_mac", _replying(reply))

    assert IpscoutNeighborTable().holder_of(_IP).mac == _MAC


@pytest.mark.os_agnostic
def test_holder_of_refuses_a_reply_that_is_not_a_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = ipscout.MacLookup.model_construct(
        ip=str(_IP),
        mac="incomplete",
        scope=ipscout.MacScope.DIRECT,
        via_ip=None,
        interface=None,
        method=ipscout.MacMethod.ACTIVE,
    )
    monkeypatch.setattr(ipscout, "lookup_mac", _replying(reply))

    with pytest.raises(NeighborTableError, match=r"'incomplete' for 192\.0\.2\.77, which is not a MAC"):
        IpscoutNeighborTable().holder_of(_IP)


@pytest.mark.os_agnostic
def test_a_router_answer_is_a_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = ipscout.MacLookup(
        ip=str(_IP),
        mac="00:00:5e:00:53:01",
        scope=ipscout.MacScope.NEXT_HOP,
        via_ip="198.51.100.1",
        method=ipscout.MacMethod.ACTIVE,
    )
    monkeypatch.setattr(ipscout, "lookup_mac", _replying(reply))

    with pytest.raises(ValueError, match=r"reached through 198\.51\.100\.1"):
        IpscoutNeighborTable().holder_of(_IP)


@pytest.mark.os_agnostic
def test_a_failed_lookup_is_a_neighbor_table_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(ip: str, *, active: bool = False, fallback_to_cache: bool = False) -> ipscout.MacLookup:
        del ip, active, fallback_to_cache
        raise ipscout.IPScoutResolutionError("zone names no interface")

    monkeypatch.setattr(ipscout, "lookup_mac", failing)

    with pytest.raises(NeighborTableError, match=r"could not look up who holds 192\.0\.2\.77: zone names no interface"):
        IpscoutNeighborTable().holder_of(_IP)
