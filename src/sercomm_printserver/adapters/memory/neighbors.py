"""An in-memory neighbour table: what the ARP trick reads and writes on this host."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from ...domain.neighbor import AddressHolder, LookupMethod

if TYPE_CHECKING:
    from ipaddress import IPv4Address

    from ...domain.device_info import MacAddress


class NeighborOperation(str, Enum):
    """What a call did to the table, as :attr:`FakeNeighborTable.history` records it."""

    SET = "set"
    REMOVE = "remove"


class FakeNeighborTable:
    """Static and learned ARP entries held in a dict.

    Args:
        entries: Address to MAC, as the host has already learned them.
        method: How :meth:`holder_of` says it looked: ACTIVE stands for a host allowed to send
            ARP requests, CACHE for one that could only read its cache.

    Example:
        >>> from ipaddress import IPv4Address
        >>> from sercomm_printserver.domain.device_info import normalise_mac
        >>> table, ip = FakeNeighborTable(), IPv4Address("192.0.2.9")
        >>> table.set_static(ip, normalise_mac("00:c0:02:12:34:56"))
        >>> table.holder_of(ip).mac, table.remove(ip), table.remove(ip)
        ('00:c0:02:12:34:56', True, False)
        >>> [(operation.value, str(ip)) for operation, ip in table.history]
        [('set', '192.0.2.9'), ('remove', '192.0.2.9'), ('remove', '192.0.2.9')]
    """

    def __init__(
        self, entries: dict[IPv4Address, MacAddress] | None = None, *, method: LookupMethod = LookupMethod.ACTIVE
    ) -> None:
        self.entries: dict[IPv4Address, MacAddress] = dict(entries or {})
        self.method = method
        self.history: list[tuple[NeighborOperation, IPv4Address]] = []
        """Every set and remove in call order, with the address it named."""

    def set_static(self, ip: IPv4Address, mac: MacAddress) -> None:
        """Record the static entry."""
        self.entries[ip] = mac
        self.history.append((NeighborOperation.SET, ip))

    def remove(self, ip: IPv4Address) -> bool:
        """Drop the entry; True when there was one."""
        self.history.append((NeighborOperation.REMOVE, ip))
        return self.entries.pop(ip, None) is not None

    def holder_of(self, ip: IPv4Address) -> AddressHolder:
        """Return the mapped MAC, or None, as looked up by :attr:`method`."""
        return AddressHolder(mac=self.entries.get(ip), method=self.method)


__all__ = ["FakeNeighborTable", "NeighborOperation"]
