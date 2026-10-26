"""Who holds an address on this host's network, and how that was found out.

The ARP trick borrows an address for the device, so it must know the address is free. Only an
ARP request on the wire can show that: this host's cache knows just the hosts it has already
talked to, and measured on the network the test device sits on, a cache read reported nobody
at the address of a live print server. The answer therefore carries how it was obtained.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from .device_info import MacAddress


class LookupMethod(str, Enum):
    """How the holder of an address was looked up.

    Attributes:
        ACTIVE: An ARP request was sent and the reply (or the silence) is the answer.
        CACHE: Only this host's ARP cache was read; an empty answer proves nothing.
    """

    ACTIVE = "active"
    CACHE = "cache"


class AddressHolder(BaseModel, frozen=True, extra="forbid"):
    """The MAC that holds an address, or None, and how that was looked up.

    Example:
        >>> AddressHolder(mac=None, method=LookupMethod.ACTIVE).is_known_free
        True
        >>> AddressHolder(mac=None, method=LookupMethod.CACHE).is_known_free
        False
    """

    mac: MacAddress | None
    method: LookupMethod

    @property
    def is_known_free(self) -> bool:
        """True only when an ARP request was sent and nobody answered it."""
        return self.mac is None and self.method is LookupMethod.ACTIVE


__all__ = ["AddressHolder", "LookupMethod"]
