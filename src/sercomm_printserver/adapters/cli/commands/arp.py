"""ARP-trick commands: reach a print server by its MAC through an address borrowed for the call.

This host maps ``--ip`` to ``--mac`` with a static ARP entry, talks to the device at that address
over FTP, and removes the entry again, whatever happened. Writing the entry needs root or
``CAP_NET_ADMIN`` on Linux, root on macOS and Administrator on Windows (exit 13 without).

``--ip`` must be a FREE address inside one of this host's subnets: an address that answers is
refused, and an address outside every local subnet would go to the gateway instead of the entry.
``reach`` only reads; ``assign-ip`` needs ``--yes``; ``factory-reset`` also needs
``--confirm-name`` with the default name ``SC`` + the MAC's last six hex digits, checked against
the device itself before anything is changed.
"""

from __future__ import annotations

from ipaddress import IPv4Address
from typing import TYPE_CHECKING, TypeVar

import rich_click as click

from sercomm_printserver.application import arp_trick
from sercomm_printserver.domain.errors import ConfirmationRequiredError

from ..constants import CLICK_CONTEXT_SETTINGS
from ..typed_click import option
from ._device import DeviceFlags, run_endpoint_command, session_options

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from sercomm_printserver.adapters.config.device_settings import DeviceSettings
    from sercomm_printserver.application.arp_trick import ArpResult
    from sercomm_printserver.application.print_server import PrintServer
    from sercomm_printserver.composition import AppServices
    from sercomm_printserver.domain.endpoint import DeviceEndpoint

_F = TypeVar("_F", bound="Callable[..., Any]")


def _arp_options(command: _F) -> _F:
    """Add ``--mac``, ``--ip`` and ``--interface`` to an ARP command."""
    decorators = (
        option("--mac", type=str, required=True, help="Hardware address of the print server."),
        option("--ip", type=str, required=True, help="A free address in this host's subnet to borrow for the call."),
        option(
            "--interface",
            type=str,
            default=None,
            help="Interface for the ARP entry, by name or index. Defaults to the one whose subnet holds --ip.",
        ),
    )
    wrapped: Any = command
    for decorator in reversed(decorators):
        wrapped = decorator(wrapped)
    return wrapped


def _opener(services: AppServices, settings: DeviceSettings) -> Callable[[DeviceEndpoint], PrintServer]:
    def open_server(endpoint: DeviceEndpoint) -> PrintServer:
        return services.open_print_server(endpoint, raw_port_base=settings.raw_port_base)

    return open_server


def _render(result: ArpResult) -> str:
    lines = [
        f"device:      {result.device.default_name} ({result.mac_address})",
        f"server name: {result.device.server_name}",
        f"firmware:    {result.device.firmware_version}",
        f"borrowed:    {result.borrowed_ip} (static ARP entry removed again)",
    ]
    if result.write is not None:
        changed = ", ".join(change.token for change in result.write.changes) or "nothing"
        lines.append(f"changed:     {changed}")
        if result.write.reachable_at is not None:
            lines.append(f"answers at:  {result.write.reachable_at}")
    return "\n".join(lines)


@click.group("arp", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_arp() -> None:
    """Reach a print server by its MAC through a borrowed address (needs admin rights)."""


@cli_arp.command("reach", context_settings=CLICK_CONTEXT_SETTINGS)
@_arp_options
@session_options
@click.pass_context
def cli_arp_reach(
    ctx: click.Context,
    *,
    mac: str,
    ip: str,
    interface: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Read the device's identity at the borrowed address; changes nothing on the device."""

    def work(endpoint: DeviceEndpoint, services: AppServices, settings: DeviceSettings) -> ArpResult:
        table = services.open_neighbor_table(interface=interface)
        return arp_trick.reach(table, _opener(services, settings), endpoint=endpoint, mac=mac)

    flags = DeviceFlags(host=ip, timeout=timeout, as_json=as_json, as_json_bare=as_json_bare)
    run_endpoint_command(ctx, command="arp reach", flags=flags, work=work, human=_render)


@cli_arp.command("assign-ip", context_settings=CLICK_CONTEXT_SETTINGS)
@_arp_options
@option("--netmask", type=str, default=None, help="Netmask to store with the address (default: keep the device's).")
@option("--gateway", type=str, default=None, help="Gateway to store with the address (default: keep the device's).")
@option("--yes", is_flag=True, default=False, help="Confirm that the device should be changed.")
@session_options
@click.pass_context
def cli_arp_assign_ip(
    ctx: click.Context,
    *,
    mac: str,
    ip: str,
    interface: str | None,
    netmask: str | None,
    gateway: str | None,
    yes: bool,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Store --ip as the device's static address (DHCP off) and restart it there."""

    def work(endpoint: DeviceEndpoint, services: AppServices, settings: DeviceSettings) -> ArpResult:
        if not yes:
            raise ConfirmationRequiredError("arp assign-ip changes the device; pass --yes to do it")
        table = services.open_neighbor_table(interface=interface)
        return arp_trick.assign_ip(
            table,
            _opener(services, settings),
            endpoint=endpoint,
            mac=mac,
            netmask=_address(netmask, what="--netmask"),
            gateway=_address(gateway, what="--gateway"),
        )

    flags = DeviceFlags(host=ip, timeout=timeout, as_json=as_json, as_json_bare=as_json_bare)
    run_endpoint_command(ctx, command="arp assign-ip", flags=flags, work=work, human=_render)


@cli_arp.command("factory-reset", context_settings=CLICK_CONTEXT_SETTINGS)
@_arp_options
@option("--yes", is_flag=True, default=False, help="Confirm that the device should be changed.")
@option(
    "--confirm-name",
    type=str,
    default="",
    help="The device's default name, SC + the last six hex digits of --mac, as confirmation.",
)
@session_options
@click.pass_context
def cli_arp_factory_reset(
    ctx: click.Context,
    *,
    mac: str,
    ip: str,
    interface: str | None,
    yes: bool,
    confirm_name: str,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Restore factory settings of the device behind --mac. Its IP becomes 0.0.0.0 afterwards."""

    def work(endpoint: DeviceEndpoint, services: AppServices, settings: DeviceSettings) -> ArpResult:
        if not yes:
            raise ConfirmationRequiredError("arp factory-reset changes the device; pass --yes to do it")
        table = services.open_neighbor_table(interface=interface)
        return arp_trick.factory_reset(
            table, _opener(services, settings), endpoint=endpoint, mac=mac, confirm_name=confirm_name
        )

    flags = DeviceFlags(host=ip, timeout=timeout, as_json=as_json, as_json_bare=as_json_bare)
    run_endpoint_command(ctx, command="arp factory-reset", flags=flags, work=work, human=_render)


def _address(value: str | None, *, what: str) -> IPv4Address | None:
    """Parse an optional IPv4 option at the boundary; a malformed one is a ValueError (exit 22)."""
    if value is None:
        return None
    try:
        return IPv4Address(value.strip())
    except ValueError as error:
        raise ValueError(f"{what} {value!r} is not an IPv4 address") from error


__all__ = ["cli_arp"]
