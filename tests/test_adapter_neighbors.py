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

    with pytest.raises(HostPrivilegeError, match="CAP_NET_ADMIN"):
        IpscoutNeighborTable(interface=route.interface).set_static(_IP, _MAC)


@pytest.mark.os_agnostic
def test_mac_of_an_address_nobody_holds_is_none() -> None:
    assert IpscoutNeighborTable().mac_of(IPv4Address("192.0.2.254")) is None


# ipscout's reply is the third-party edge the adapter normalises; the tests below substitute
# that reply, since no host can be made to hold a chosen MAC without writing its table.


def _replying(reply: str) -> Callable[..., str]:
    """Return a stand-in for ``ipscout.get_mac_address`` that always answers ``reply``."""

    def get_mac_address(ip: str, *, active: bool = False) -> str:
        del ip, active
        return reply

    return get_mac_address


@pytest.mark.os_agnostic
def test_mac_of_normalises_the_spelling_ipscout_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ipscout, "get_mac_address", _replying("00-00-5E-00-53-07"))

    assert IpscoutNeighborTable().mac_of(_IP) == _MAC


@pytest.mark.os_agnostic
def test_mac_of_refuses_a_reply_that_is_not_a_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ipscout, "get_mac_address", _replying("incomplete"))

    with pytest.raises(NeighborTableError, match=r"'incomplete' for 192\.0\.2\.77, which is not a MAC"):
        IpscoutNeighborTable().mac_of(_IP)
