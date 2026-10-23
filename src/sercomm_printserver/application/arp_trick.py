"""Reach a print server by its MAC alone: the vendor manuals' "ARP trick", rebuilt on measurements.

The manuals map a new IP to the device's MAC with ``arp -s``, then use TFTP (``get SETIP``,
``get DEFAULTC``). Measured on a PS301: the device answers packets to ANY address mapped to
its MAC, but refuses action files over TFTP. So the trick here keeps the static entry only as
long as it takes to talk to the device over FTP at the borrowed address:

* :func:`assign_ip` writes the new address into the device's CONFIG and restarts it there - the
  same verified path as any configuration change - so the device ends with a static IP no
  matter which address it had before.
* :func:`factory_reset` restores factory settings of a device whose address is unknown. It
  first reads PSINF over the borrowed address and refuses unless the device's default name
  matches both the MAC and the name the caller repeated.

The static entry is removed again in every case.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ..domain.config_codec import with_value
from ..domain.device_info import DeviceInfo, mac_from_default_name, normalise_mac
from ..domain.errors import ConfirmationRequiredError
from .print_server import ConfigWriteResult

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from ipaddress import IPv4Address

    from ..domain.endpoint import DeviceEndpoint
    from .ports import NeighborTable
    from .print_server import PrintServer


class ArpResult(BaseModel, frozen=True, extra="forbid"):
    """What an ARP-trick operation did."""

    mac_address: str
    borrowed_ip: str
    device: DeviceInfo
    write: ConfigWriteResult | None = None


@contextlib.contextmanager
def borrowed_address(table: NeighborTable, *, ip: str, mac: str) -> Generator[None, None, None]:
    """Map ``ip`` to ``mac`` for the duration of the block, refusing an address in use.

    Raises:
        ValueError: This host already maps ``ip`` to another MAC - something else holds it.
    """
    holder = table.mac_of(ip)
    if holder is not None and normalise_mac(holder) != normalise_mac(mac):
        raise ValueError(f"{ip} belongs to {holder} on this network; borrow a free address")
    table.set_static(ip, mac)
    try:
        yield
    finally:
        table.remove(ip)


def reach(
    table: NeighborTable, open_server: Callable[[DeviceEndpoint], PrintServer], *, endpoint: DeviceEndpoint, mac: str
) -> ArpResult:
    """Read the device's PSINF over a borrowed address; changes nothing on the device."""
    mac = normalise_mac(mac)
    with borrowed_address(table, ip=endpoint.host, mac=mac):
        device = _identified(open_server(endpoint), mac)
    return ArpResult(mac_address=mac, borrowed_ip=endpoint.host, device=device)


def assign_ip(
    table: NeighborTable,
    open_server: Callable[[DeviceEndpoint], PrintServer],
    *,
    endpoint: DeviceEndpoint,
    mac: str,
    netmask: IPv4Address | None = None,
    gateway: IPv4Address | None = None,
) -> ArpResult:
    """Give the device behind ``mac`` the static address ``endpoint.host`` and restart it there.

    Raises:
        DeviceResponseError: The device behind the MAC is not one of this family, or stored
            something else than was written.
        ValueError: ``mac`` is not a MAC address.
    """
    mac = normalise_mac(mac)
    with borrowed_address(table, ip=endpoint.host, mac=mac):
        server = open_server(endpoint)
        device = _identified(server, mac)
        new = with_value(with_value(server.read_config(), "IP_ADDR", endpoint.host), "DHCP_MODE", "Disable")
        if netmask is not None:
            new = with_value(new, "MASK", str(netmask))
        if gateway is not None:
            new = with_value(new, "GATEWAY", str(gateway))
        result = server.write_config(new)
    return ArpResult(mac_address=mac, borrowed_ip=endpoint.host, device=device, write=result)


def factory_reset(
    table: NeighborTable,
    open_server: Callable[[DeviceEndpoint], PrintServer],
    *,
    endpoint: DeviceEndpoint,
    mac: str,
    confirm_name: str,
) -> ArpResult:
    """Restore factory settings of the device behind ``mac``; its IP becomes 0.0.0.0 afterwards.

    Raises:
        ConfirmationRequiredError: ``confirm_name`` is not the device's default name derived
            from ``mac``.
    """
    mac = normalise_mac(mac)
    expected = "SC" + mac.replace(":", "")[-6:].upper()
    if confirm_name.strip().upper() != expected:
        raise ConfirmationRequiredError(f"factory reset by MAC needs the device's default name {expected}")
    with borrowed_address(table, ip=endpoint.host, mac=mac):
        server = open_server(endpoint)
        device = _identified(server, mac)
        server.factory_default(confirm_name=device.default_name)
    return ArpResult(mac_address=mac, borrowed_ip=endpoint.host, device=device)


def _identified(server: PrintServer, mac: str) -> DeviceInfo:
    """Read PSINF and require that the device's own default name matches ``mac``."""
    device = server.info()
    derived = mac_from_default_name(device.default_name)
    if derived is None or derived != normalise_mac(mac):
        raise ConfirmationRequiredError(
            f"the device at the borrowed address calls itself {device.default_name}, which is not MAC {mac}"
        )
    return device


__all__ = ["ArpResult", "assign_ip", "borrowed_address", "factory_reset", "reach"]
