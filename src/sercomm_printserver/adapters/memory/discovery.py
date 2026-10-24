"""An in-memory network for discovery: hosts that greet like print servers, or not."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network
from typing import TYPE_CHECKING

from ...application.discovery import PRINT_SERVER_GREETING, ProbeHit
from ...domain.device_info import normalise_mac

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ...domain.device_info import MacAddress


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
        # Parsed once, so a malformed fixture MAC fails here rather than at the first lookup.
        self._macs: dict[IPv4Address, MacAddress] = {
            IPv4Address(host): normalise_mac(mac) for host, mac in (macs or {}).items()
        }
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

    def mac_address(self, host: IPv4Address) -> MacAddress | None:
        """Return the configured MAC address, normalised like the real scanner's."""
        return self._macs.get(host)


__all__ = ["FakeScanner"]
