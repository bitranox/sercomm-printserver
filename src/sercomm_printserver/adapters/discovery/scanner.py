"""Probe hosts' FTP port, find MAC addresses and local networks - all through ipscout.

A probe connects, reads the greeting and says ``QUIT`` - nothing else, to any host. A sweep
reaches every device on the network, production print servers included, so it asks the least
it can: firmware 6A10 answers ``SYST`` with random memory instead of its version, and one such
device stopped serving FTP, Telnet and LPD until power-cycled after a session of repeated probes
(cause not isolated). It never logs in and never touches a print port. ipscout reads the
neighbour cache passively (no privileges), and the probe's own connection put the device there.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network, IPv6Network
from typing import TYPE_CHECKING, Final

import ipscout

from ...application.discovery import LocalScope, ProbeHit
from ...domain.device_info import MacAddress, normalise_mac

if TYPE_CHECKING:
    from collections.abc import Sequence

#: An FTP reply line is short; more than this without a line end is not an FTP server.
_LINE_LIMIT: Final = 512
_QUIT: Final = b"QUIT\r\n"


class FtpBannerScanner:
    """Implements :class:`~sercomm_printserver.application.ports.HostScanner`.

    Args:
        workers: Probes in flight at once.
        ftp_port: Port to probe; 21 on a real device, anything for a test server.
    """

    def __init__(self, *, workers: int = 64, ftp_port: int = 21) -> None:
        self._workers = workers
        self._ftp_port = ftp_port

    def local_scope(self, *, limit: int) -> LocalScope:
        """Return ipscout's sweep plan for this host's networks under a budget of ``limit``."""
        scope = ipscout.sweep_scope(limit=limit)
        return LocalScope(networks=_ipv4(scope.networks), skipped=_ipv4(scope.skipped))

    def probe_ftp(self, hosts: Sequence[str], *, timeout: float) -> tuple[ProbeHit, ...]:
        """Probe ``hosts`` concurrently; return the ones that greeted as an FTP server.

        The greeting is read and ``QUIT`` sent on the one connection per host: a PS301 refuses
        a new connection for about 0.1 s after each session, so a port scan first would hide it.
        """
        if not hosts:
            return ()
        banners = ipscout.grab_banners(
            hosts,
            self._ftp_port,
            timeout=timeout,
            max_line_bytes=_LINE_LIMIT,
            farewell=_QUIT,
            concurrency=min(self._workers, len(hosts)),
        )
        return tuple(
            ProbeHit(host=IPv4Address(banner.host), greeting=banner.line)
            for banner in banners.values()
            if banner.state is ipscout.BannerState.GREETED and banner.line is not None and banner.line.startswith("220")
        )

    def mac_address(self, host: IPv4Address) -> MacAddress | None:
        """Return the MAC this host's neighbour cache holds for ``host``, normalised, or None.

        A cache entry that is not a MAC address reads as no entry: the MAC is optional in a
        discovery report, and one odd entry must not end a sweep over a whole network.
        """
        try:
            raw = ipscout.get_mac_address(str(host))
            return None if raw is None else normalise_mac(raw)
        except (ipscout.IPScoutError, ValueError):
            return None


def _ipv4(networks: tuple[IPv4Network | IPv6Network, ...]) -> tuple[IPv4Network, ...]:
    """Keep the IPv4 networks: the probe and the MAC lookup are IPv4 only."""
    return tuple(network for network in networks if isinstance(network, IPv4Network))


__all__ = ["FtpBannerScanner"]
