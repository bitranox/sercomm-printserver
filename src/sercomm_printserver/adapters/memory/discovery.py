"""An in-memory network for discovery: hosts that greet like print servers, or not."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network
from typing import TYPE_CHECKING

from ...application.discovery import PRINT_SERVER_GREETING, ProbeHit

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class FakeScanner:
    """Answers probes from a fixed table.

    Args:
        hits: Host addresses that greet as print servers.
        others: Host address to its greeting, for FTP servers that are not print servers.
        macs: Host address to MAC address, as the neighbour cache would know it.
        networks: What :meth:`local_networks` reports.
    """

    def __init__(
        self,
        *,
        hits: Sequence[str],
        others: Mapping[str, str] | None = None,
        macs: Mapping[str, str] | None = None,
        networks: tuple[IPv4Network, ...] = (IPv4Network("192.0.2.0/24"),),
    ) -> None:
        self._hits = set(hits)
        self._others = dict(others or {})
        self._macs = dict(macs or {})
        self._networks = networks
        self.probed: list[str] = []

    def local_networks(self) -> tuple[IPv4Network, ...]:
        """Return the configured networks."""
        return self._networks

    def probe_ftp(self, hosts: Sequence[str], *, timeout: float) -> tuple[ProbeHit, ...]:
        """Answer from the tables; records every host asked."""
        del timeout  # an in-memory probe does not wait
        self.probed.extend(hosts)
        found = [
            ProbeHit(host=IPv4Address(host), greeting=f"{PRINT_SERVER_GREETING}.")
            for host in hosts
            if host in self._hits
        ]
        found += [
            ProbeHit(host=IPv4Address(host), greeting=self._others[host]) for host in hosts if host in self._others
        ]
        return tuple(found)

    def mac_address(self, host: str) -> str | None:
        """Return the configured MAC address."""
        return self._macs.get(host)


__all__ = ["FakeScanner"]
