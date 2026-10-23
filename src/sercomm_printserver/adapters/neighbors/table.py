"""This host's neighbour table, written natively through ipscout: the means of the ARP trick.

ipscout writes a permanent IPv4 entry with netlink on Linux, the IP Helper API on Windows and a
routing socket on macOS - no ``arp -s`` subprocess, so no locale-dependent output to parse. The
write needs root or ``CAP_NET_ADMIN`` on Linux, root on macOS and Administrator on Windows;
ipscout's refusal becomes :class:`~sercomm_printserver.domain.errors.HostPrivilegeError` here, so
callers above the adapter layer never import ipscout.

Whether an address is free is asked ACTIVELY when ipscout can (an ARP request on the wire): a
passive cache read only knows the hosts this machine has already talked to, and borrowing an
address a silent printer or laptop holds would send that host's traffic to the print server.
"""

from __future__ import annotations

import ipscout

from ...domain.errors import HostPrivilegeError, NeighborTableError


class IpscoutNeighborTable:
    """Implements :class:`~sercomm_printserver.application.ports.NeighborTable`.

    Args:
        interface: The interface for every entry, by name or index; ``None`` lets ipscout pick
            the one interface whose subnet holds the address.
    """

    def __init__(self, *, interface: str | None = None) -> None:
        self._interface = interface

    def set_static(self, ip: str, mac: str) -> None:
        """Map ``ip`` to ``mac`` permanently.

        Raises:
            HostPrivilegeError: This process may not change the neighbour table.
            ValueError: ``ip`` or ``mac`` cannot name one station, or no single local interface
                holds ``ip`` and none was configured.
            NeighborTableError: The operating system refused for another reason.
        """
        try:
            ipscout.set_neighbour(ip, mac, interface=self._interface)
        except ipscout.IPScoutPermissionError as error:
            raise HostPrivilegeError(str(error)) from error
        except ipscout.IPScoutUnsupportedError as error:
            raise ValueError(str(error)) from error
        except ipscout.IPScoutError as error:
            raise NeighborTableError(str(error)) from error

    def remove(self, ip: str) -> bool:
        """Remove the entry for ``ip``; True when there was one.

        Raises:
            HostPrivilegeError: This process may not change the neighbour table.
            NeighborTableError: The operating system refused for another reason.
        """
        try:
            return ipscout.remove_neighbour(ip, interface=self._interface)
        except ipscout.IPScoutPermissionError as error:
            raise HostPrivilegeError(str(error)) from error
        except ipscout.IPScoutError as error:
            raise NeighborTableError(str(error)) from error

    def mac_of(self, ip: str) -> str | None:
        """Return the MAC that holds ``ip`` on the wire, or None when nothing answers.

        Asks with an ARP request where ipscout can; where it cannot (no privilege for an active
        request), falls back to the passive cache, which knows only hosts already talked to.
        """
        try:
            return ipscout.get_mac_address(ip, active=True)
        except ipscout.IPScoutError:
            return ipscout.get_mac_address(ip)


__all__ = ["IpscoutNeighborTable"]
