"""An in-memory neighbour table: what the ARP trick reads and writes on this host."""

from __future__ import annotations


class FakeNeighborTable:
    """Static and learned ARP entries held in a dict.

    Args:
        entries: Address to MAC, as the host has already learned them.

    Example:
        >>> table = FakeNeighborTable()
        >>> table.set_static("192.0.2.9", "00:c0:02:12:34:56")
        >>> table.mac_of("192.0.2.9"), table.remove("192.0.2.9"), table.remove("192.0.2.9")
        ('00:c0:02:12:34:56', True, False)
    """

    def __init__(self, entries: dict[str, str] | None = None) -> None:
        self.entries: dict[str, str] = dict(entries or {})
        self.history: list[tuple[str, str]] = []

    def set_static(self, ip: str, mac: str) -> None:
        """Record the static entry."""
        self.entries[ip] = mac
        self.history.append(("set", ip))

    def remove(self, ip: str) -> bool:
        """Drop the entry; True when there was one."""
        self.history.append(("remove", ip))
        return self.entries.pop(ip, None) is not None

    def mac_of(self, ip: str) -> str | None:
        """Return the mapped MAC, or None."""
        return self.entries.get(ip)


__all__ = ["FakeNeighborTable"]
