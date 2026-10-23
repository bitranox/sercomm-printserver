"""Public package surface: talk to a SerComm print server from Python.

Typical use::

    from sercomm_printserver import DeviceEndpoint, PrintJob, open_print_server

    server = open_print_server(DeviceEndpoint(host="192.0.2.52"))
    server.print_lpd("L1", PrintJob(data=b"hello\\r\\n\\f", name="greeting"))
    print(server.info().firmware_version)

Finding devices: :func:`discover_print_servers`. Reaching a device by its MAC through a borrowed
address (the ARP trick, needs admin rights): :mod:`arp_trick` with :class:`IpscoutNeighborTable`.
Every failure is one of the exceptions exported here; see each method's ``Raises``.
"""

from __future__ import annotations

from ipaddress import IPv4Network

# Metadata
from .__init__conf__ import print_info
from .adapters.discovery import FtpBannerScanner
from .adapters.neighbors import IpscoutNeighborTable
from .application import arp_trick
from .application.discovery import DiscoveredDevice, DiscoveryReport, discover
from .application.print_server import ConfigWriteResult, PrintServer

# Composition exports (wired adapters)
from .composition import get_config, open_print_server
from .domain.config_codec import ConfigChange, parse_config, render_config, with_value
from .domain.config_model import DeviceConfig
from .domain.device_info import DeviceInfo
from .domain.endpoint import DeviceEndpoint, PrintJob
from .domain.errors import (
    AuthenticationRequiredError,
    ConfigFormatError,
    ConfigurationError,
    ConfirmationRequiredError,
    DeviceResponseError,
    DeviceUnavailableError,
    HostPrivilegeError,
    NeighborTableError,
)
from .domain.port_status import PortStatus


def discover_print_servers(*, networks: list[str] | None = None, timeout: float = 3.0) -> DiscoveryReport:
    """Find the family's print servers by their FTP greeting; never logs in, never prints.

    Args:
        networks: CIDR networks to search (``"192.0.2.0/24"``); None searches this host's own.
        timeout: Seconds to wait for each host's greeting.

    Returns:
        The devices found, with the MAC this host's neighbour cache holds for each.

    Raises:
        ValueError: A network is not an IPv4 CIDR.
    """
    chosen = [_network(network) for network in networks] if networks else None
    return discover(FtpBannerScanner(), networks=chosen, timeout=timeout)


def _network(text: str) -> IPv4Network:
    try:
        return IPv4Network(text.strip(), strict=False)
    except ValueError as error:
        raise ValueError(f"{text!r} is not an IPv4 network: {error}") from error


__all__ = [
    "AuthenticationRequiredError",
    "ConfigChange",
    "ConfigFormatError",
    "ConfigWriteResult",
    "ConfigurationError",
    "ConfirmationRequiredError",
    "DeviceConfig",
    "DeviceEndpoint",
    "DeviceInfo",
    "DeviceResponseError",
    "DeviceUnavailableError",
    "DiscoveredDevice",
    "DiscoveryReport",
    "HostPrivilegeError",
    "IpscoutNeighborTable",
    "NeighborTableError",
    "PortStatus",
    "PrintJob",
    "PrintServer",
    "arp_trick",
    "discover_print_servers",
    "get_config",
    "open_print_server",
    "parse_config",
    "print_info",
    "render_config",
    "with_value",
]
