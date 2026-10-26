"""Reach a print server by its MAC alone: the vendor manuals' "ARP trick", rebuilt on measurements.

The manuals map a new IP to the device's MAC with ``arp -s``, then use TFTP (``get SETIP``,
``get DEFAULTC``). Measured on a PS301: the device answers packets to ANY address mapped to
its MAC. TFTP carries some action files (``RESET`` restarts it) but refuses ``PASSRESET``,
and it reports nothing back, so the trick here talks FTP at the borrowed address - the path
every other change uses - and keeps the static entry only as long as that takes:

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
from ipaddress import IPv4Address
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ..domain.device_info import DeviceInfo, MacAddress, default_name_from_mac, mac_from_default_name, normalise_mac
from ..domain.errors import ConfigFormatError, ConfirmationRequiredError, UnverifiedAddressError
from .print_server import ConfigWriteResult

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from ..domain.config_model import DeviceConfig
    from ..domain.endpoint import DeviceEndpoint
    from .ports import NeighborTable
    from .print_server import PrintServer


class ArpResult(BaseModel, frozen=True, extra="forbid"):
    """What an ARP-trick operation did."""

    mac_address: MacAddress
    borrowed_ip: IPv4Address
    device: DeviceInfo
    write: ConfigWriteResult | None = None


@contextlib.contextmanager
def borrowed_address(table: NeighborTable, *, ip: IPv4Address, mac: MacAddress) -> Generator[None, None, None]:
    """Map ``ip`` to ``mac`` for the duration of the block, refusing an address in use.

    ``mac`` is normalised already, as the table reports its holders, so the two compare as
    they are; :func:`~sercomm_printserver.domain.device_info.normalise_mac` makes one.

    Raises:
        ValueError: Another MAC holds ``ip`` on this network.
        UnverifiedAddressError: This host could not send an ARP request and its cache does not
            know ``ip``, so nothing shows the address is free.
    """
    holder = table.holder_of(ip)
    if holder.mac is not None and holder.mac != mac:
        raise ValueError(f"{ip} belongs to {holder.mac} on this network; borrow a free address")
    if holder.mac is None and not holder.is_known_free:
        # Refused, not warned (user decision 2026-10-26): measured, a cache read reported nobody at
        # the address of a live print server, and a borrowed address that is in use sends its
        # holder's traffic to the device.
        raise UnverifiedAddressError(
            f"cannot tell whether {ip} is free: this host could not send an ARP request (it needs root or "
            f"CAP_NET_RAW on Linux, root on macOS, or an interface that reaches {ip}) and its ARP cache "
            "does not know the address"
        )
    table.set_static(ip, mac)
    try:
        yield
    finally:
        table.remove(ip)


def reach(
    table: NeighborTable,
    open_server: Callable[[DeviceEndpoint], PrintServer],
    *,
    endpoint: DeviceEndpoint,
    ip: IPv4Address,
    mac: str,
) -> ArpResult:
    """Read the device's PSINF over the borrowed address ``ip``; changes nothing on the device.

    Args:
        table: This host's neighbour table.
        open_server: Returns the print server at an endpoint.
        endpoint: Login, password and timeouts for the session; its host is replaced by ``ip``.
        ip: A free address in this host's subnet to borrow for the call.
        mac: The device's MAC in any common spelling (colons, dashes, none, Cisco dots).

    Raises:
        ValueError: ``mac`` is not a MAC address, or something else holds ``ip``.
        UnverifiedAddressError: Nothing shows ``ip`` is free: no ARP request could be sent and
            this host's cache does not know the address.
    """
    device_mac = normalise_mac(mac)
    with borrowed_address(table, ip=ip, mac=device_mac):
        device = _identified(open_server(_at(endpoint, ip)), device_mac)
    return ArpResult(mac_address=device_mac, borrowed_ip=ip, device=device)


def assign_ip(
    table: NeighborTable,
    open_server: Callable[[DeviceEndpoint], PrintServer],
    *,
    endpoint: DeviceEndpoint,
    ip: IPv4Address,
    mac: str,
    netmask: IPv4Address | None = None,
    gateway: IPv4Address | None = None,
) -> ArpResult:
    """Give the device behind ``mac`` the static address ``ip`` and restart it there.

    ``ip`` is both the address borrowed for the call and the one stored; ``endpoint`` carries
    the session's login, password and timeouts, its host is replaced by ``ip``.

    Raises:
        ConfigFormatError: The device's firmware has no DHCP switch (6A10), so its address
            cannot be made static here.
        DeviceResponseError: The device behind the MAC is not one of this family, or stored
            something else than was written.
        ValueError: ``mac`` is not a MAC address, or something else holds ``ip``.
        UnverifiedAddressError: Nothing shows ``ip`` is free: no ARP request could be sent and
            this host's cache does not know the address.
    """
    device_mac = normalise_mac(mac)
    with borrowed_address(table, ip=ip, mac=device_mac):
        server = open_server(_at(endpoint, ip))
        device = _identified(server, device_mac)
        new = _static_at(server.read_config(), address=ip, netmask=netmask, gateway=gateway)
        result = server.write_config(new)
    return ArpResult(mac_address=device_mac, borrowed_ip=ip, device=device, write=result)


def factory_reset(
    table: NeighborTable,
    open_server: Callable[[DeviceEndpoint], PrintServer],
    *,
    endpoint: DeviceEndpoint,
    ip: IPv4Address,
    mac: str,
    confirm_name: str,
) -> ArpResult:
    """Restore factory settings of the device behind ``mac``; its IP becomes 0.0.0.0 afterwards.

    ``endpoint`` carries the session's login, password and timeouts; its host is replaced by
    the borrowed address ``ip``.

    Raises:
        ConfirmationRequiredError: ``confirm_name`` is not the device's default name derived
            from ``mac``.
        ValueError: ``mac`` is not a MAC address, or something else holds ``ip``.
        UnverifiedAddressError: Nothing shows ``ip`` is free: no ARP request could be sent and
            this host's cache does not know the address.
    """
    device_mac = normalise_mac(mac)
    expected = default_name_from_mac(device_mac)
    if confirm_name.strip().upper() != expected:
        raise ConfirmationRequiredError(f"factory reset by MAC needs the device's default name {expected}")
    with borrowed_address(table, ip=ip, mac=device_mac):
        server = open_server(_at(endpoint, ip))
        device = _identified(server, device_mac)
        server.factory_default(confirm_name=device.default_name)
    return ArpResult(mac_address=device_mac, borrowed_ip=ip, device=device)


def _at(endpoint: DeviceEndpoint, ip: IPv4Address) -> DeviceEndpoint:
    """Return ``endpoint`` at the borrowed address.

    The endpoint's host is text because it also names devices by hostname; the borrowed
    address is IPv4, since this host writes static neighbour entries for IPv4 only.
    """
    return endpoint.model_copy(update={"host": str(ip)})


def _static_at(
    config: DeviceConfig, *, address: IPv4Address, netmask: IPv4Address | None, gateway: IPv4Address | None
) -> DeviceConfig:
    """Return ``config`` with a static ``address``: DHCP off, netmask and gateway replaced when given.

    Raises:
        ConfigFormatError: ``config`` has no DHCP switch to turn off (firmware 6A10).
    """
    tcp_ip = config.tcp_ip
    if tcp_ip.dhcp is None:
        # Firmware 6A10 has no switch, and nothing measured shows it keeps a stored address
        # rather than asking DHCP: refuse instead of risking a device that leaves the network.
        raise ConfigFormatError("no parameter 'DHCP_MODE' in this configuration")
    static = tcp_ip.model_copy(
        update={
            "ip_address": address,
            "dhcp": False,
            "netmask": tcp_ip.netmask if netmask is None else netmask,
            "gateway": tcp_ip.gateway if gateway is None else gateway,
        }
    )
    return config.model_copy(update={"tcp_ip": static})


def _identified(server: PrintServer, mac: MacAddress) -> DeviceInfo:
    """Read PSINF and require that the device's own default name matches ``mac``."""
    device = server.info()
    if mac_from_default_name(device.default_name) != mac:
        raise ConfirmationRequiredError(
            f"the device at the borrowed address calls itself {device.default_name}, which is not MAC {mac}"
        )
    return device


__all__ = ["ArpResult", "assign_ip", "borrowed_address", "factory_reset", "reach"]
