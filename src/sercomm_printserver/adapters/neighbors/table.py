"""This host's neighbour table, written natively through ipscout: the means of the ARP trick.

ipscout writes a permanent IPv4 entry with netlink on Linux, the IP Helper API on Windows and a
routing socket on macOS - no ``arp -s`` subprocess, so no locale-dependent output to parse. The
write needs root or ``CAP_NET_ADMIN`` on Linux, root on macOS and Administrator on Windows;
ipscout's refusal becomes :class:`~sercomm_printserver.domain.errors.HostPrivilegeError` here, so
callers above the adapter layer never import ipscout.

Whether an address is free is asked ACTIVELY when ipscout can (an ARP request on the wire): a
passive cache read only knows the hosts this machine has already talked to, and borrowing an
address a silent printer or laptop holds would send that host's traffic to the print server.
When it cannot ask, ipscout reads the cache instead and says so; the answer carries that, and
the ARP trick refuses to borrow on a cache answer that found nobody.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ipscout

from ...domain.device_info import normalise_mac
from ...domain.errors import HostPrivilegeError, NeighborTableError
from ...domain.neighbor import AddressHolder, LookupMethod

if TYPE_CHECKING:
    from ipaddress import IPv4Address

    from ...domain.device_info import MacAddress


class IpscoutNeighborTable:
    """Implements :class:`~sercomm_printserver.application.ports.NeighborTable`.

    Args:
        interface: The interface for every entry, by name or index; ``None`` lets ipscout pick
            the one interface whose subnet holds the address.
    """

    def __init__(self, *, interface: str | None = None) -> None:
        self._interface = interface

    def set_static(self, ip: IPv4Address, mac: MacAddress) -> None:
        """Map ``ip`` to ``mac`` permanently.

        Raises:
            HostPrivilegeError: This process may not change the neighbour table.
            ValueError: ``ip`` or ``mac`` cannot name one station, or no single local interface
                holds ``ip`` and none was configured.
            NeighborTableError: The operating system refused for another reason.
        """
        try:
            ipscout.set_neighbour(str(ip), mac, interface=self._interface)
        except ipscout.IPScoutPermissionError as error:
            raise HostPrivilegeError(str(error)) from error
        except ipscout.IPScoutUnsupportedError as error:
            raise ValueError(str(error)) from error
        except ipscout.IPScoutError as error:
            raise NeighborTableError(str(error)) from error

    def remove(self, ip: IPv4Address) -> bool:
        """Remove the entry for ``ip``; True when there was one.

        Raises:
            HostPrivilegeError: This process may not change the neighbour table.
            NeighborTableError: The operating system refused for another reason.
        """
        try:
            return ipscout.remove_neighbour(str(ip), interface=self._interface)
        except ipscout.IPScoutPermissionError as error:
            raise HostPrivilegeError(str(error)) from error
        except ipscout.IPScoutError as error:
            raise NeighborTableError(str(error)) from error

    def holder_of(self, ip: IPv4Address) -> AddressHolder:
        """Return the MAC that holds ``ip``, or None, and how that was found out.

        Asks with an ARP request where ipscout can. Where it cannot (no privilege for a raw
        socket, or no interface or route that carries the request), ipscout reads the passive
        cache instead, which knows only hosts already talked to; the answer's method says which.

        Raises:
            ValueError: ``ip`` is not on this host's network: only a router answers for it.
            NeighborTableError: The lookup failed for another reason, or the operating system
                reported something that is not a MAC.
        """
        try:
            reply = ipscout.lookup_mac(str(ip), active=True, fallback_to_cache=True)
        except ipscout.IPScoutError as error:
            raise NeighborTableError(f"could not look up who holds {ip}: {error}") from error
        if reply.scope is ipscout.MacScope.NEXT_HOP:
            raise ValueError(f"{ip} is not on this host's network; it is reached through {reply.via_ip}")
        # Anything but ACTIVE reads as CACHE: only an ARP request on the wire can prove an address free.
        method = LookupMethod.ACTIVE if reply.method is ipscout.MacMethod.ACTIVE else LookupMethod.CACHE
        mac = None if reply.mac is None else _parsed_mac(reply.mac, ip=ip)
        return AddressHolder(mac=mac, method=method)


def _parsed_mac(reply: str, *, ip: IPv4Address) -> MacAddress:
    """Normalise ipscout's answer at the boundary, so callers compare MACs as they are.

    Example:
        >>> from ipaddress import IPv4Address
        >>> _parsed_mac("00-C0-02-12-34-56", ip=IPv4Address("192.0.2.77"))
        '00:c0:02:12:34:56'
    """
    try:
        return normalise_mac(reply)
    except ValueError as error:
        raise NeighborTableError(f"the neighbour table holds {reply!r} for {ip}, which is not a MAC") from error


__all__ = ["IpscoutNeighborTable"]
