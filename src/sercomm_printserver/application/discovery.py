"""Find SerComm print servers on a network by their FTP greeting.

Every member of the family greets an FTP client with ``220 Print Server Ready.`` and answers
``SYST`` with its firmware version, without a login. Asking port 21 is therefore a probe that
finds every OEM variant whatever its MAC vendor prefix, and that never touches a print port
(a bare connect to a RAW port occupies it for minutes). The MAC address comes from this host's
neighbour cache afterwards, which the probe's own connection has just filled.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel

from ..domain.device_info import parse_firmware_reply
from ..domain.errors import DeviceResponseError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .ports import HostScanner

#: The greeting that identifies the family; the trailing period is optional in the match.
PRINT_SERVER_GREETING: Final = "220 Print Server Ready"
#: Upper bound on addresses one discovery probes, so a mistyped /8 cannot run for hours.
MAX_HOSTS: Final = 4096


class ProbeHit(BaseModel, frozen=True, extra="forbid"):
    """One host that answered on port 21: its greeting and its reply to ``SYST``."""

    host: IPv4Address
    greeting: str
    system_reply: str


class DiscoveredDevice(BaseModel, frozen=True, extra="forbid"):
    """A print server of the family found on the network."""

    host: IPv4Address
    firmware: str | None
    mac_address: str | None


class DiscoveryReport(BaseModel, frozen=True, extra="forbid"):
    """What a discovery searched and found."""

    networks: tuple[IPv4Network, ...]
    probed: int
    devices: tuple[DiscoveredDevice, ...]
    skipped: tuple[str, ...] = ()


def discover(scanner: HostScanner, *, networks: Sequence[IPv4Network] | None, timeout: float) -> DiscoveryReport:
    """Probe every host address of ``networks`` on port 21.

    Without ``networks`` the networks this host is attached to are probed, except any that alone
    holds more than :data:`MAX_HOSTS` addresses (a container bridge is often a /16); those are
    named in :attr:`DiscoveryReport.skipped` instead.

    Raises:
        ValueError: The named networks hold more than :data:`MAX_HOSTS` addresses together.
    """
    skipped: list[str] = []
    if networks:
        chosen = tuple(networks)
    else:
        local = scanner.local_networks()
        chosen = tuple(network for network in local if network.num_addresses - 2 <= MAX_HOSTS)
        skipped = [
            f"{network}: more than {MAX_HOSTS} addresses, name it with --network"
            for network in local
            if network not in chosen
        ]
    hosts = [str(host) for network in chosen for host in network.hosts()]
    if len(hosts) > MAX_HOSTS:
        raise ValueError(f"{len(hosts)} addresses to probe, more than {MAX_HOSTS}; name a smaller network")
    hits = scanner.probe_ftp(hosts, timeout=timeout)
    family = sorted((hit for hit in hits if hit.greeting.startswith(PRINT_SERVER_GREETING)), key=lambda hit: hit.host)
    devices = tuple(_device(hit, scanner) for hit in family)
    return DiscoveryReport(networks=chosen, probed=len(hosts), devices=devices, skipped=tuple(skipped))


def _device(hit: ProbeHit, scanner: HostScanner) -> DiscoveredDevice:
    return DiscoveredDevice(
        host=hit.host, firmware=_firmware(hit.system_reply), mac_address=scanner.mac_address(str(hit.host))
    )


def _firmware(system_reply: str) -> str | None:
    try:
        return parse_firmware_reply(system_reply)
    except DeviceResponseError:
        return None


__all__ = ["MAX_HOSTS", "PRINT_SERVER_GREETING", "DiscoveredDevice", "DiscoveryReport", "ProbeHit", "discover"]
