"""Device commands: read the print server, restart it, and its guarded actions.

The guarded actions are tiered: ``reset`` and ``password set`` need ``--yes``; the actions that
can take a device off the network or open it up (``factory-default``, ``store-ip``,
``password clear``) also need ``--confirm-name`` with the device's name, which the library checks
against the device itself.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import rich_click as click
from pydantic import BaseModel, SecretStr, computed_field

from sercomm_printserver.domain.errors import ConfirmationRequiredError
from sercomm_printserver.domain.port_health import PortHealth, PortVerdict
from sercomm_printserver.domain.port_status import PortStatus

from ..constants import CLICK_CONTEXT_SETTINGS, CommandName
from ..exit_codes import ExitCode
from ..typed_click import argument, option
from ._device import DeviceFlags, device_options, run_device_command

if TYPE_CHECKING:
    from sercomm_printserver.application.print_server import PrintServer
    from sercomm_printserver.domain.device_info import DeviceInfo


class FirmwareReport(BaseModel, frozen=True):
    """Answer of ``firmware``."""

    host: str
    firmware: str


class StatusReport(BaseModel, frozen=True):
    """Answer of ``status``."""

    host: str
    ports: tuple[PortStatus, ...]


class CheckReport(BaseModel, frozen=True):
    """Answer of ``check``: :class:`~sercomm_printserver.application.print_server.CheckResult` plus the host."""

    host: str
    ports: tuple[PortHealth, ...]
    restarted: bool
    before: tuple[PortHealth, ...]

    @computed_field
    @property
    def wedged(self) -> bool:
        """Whether a port is (still) wedged."""
        return any(health.verdict is PortVerdict.WEDGED for health in self.ports)


class ActionReport(BaseModel, frozen=True):
    """Answer of a command that triggered a device action.

    ``action`` is the command that ran, so the JSON names the action by the path a script typed.
    """

    host: str
    action: CommandName
    done: bool


class QueueReport(BaseModel, frozen=True):
    """Answer of ``queue``."""

    host: str
    queue: str
    state: str


def _flags(host: str | None, timeout: float | None, as_json: bool, as_json_bare: bool) -> DeviceFlags:
    return DeviceFlags(host=host, timeout=timeout, as_json=as_json, as_json_bare=as_json_bare)


def _require_yes(yes: bool, *, what: CommandName) -> None:
    if not yes:
        raise ConfirmationRequiredError(f"{what.value} changes the device; pass --yes to do it")


# ---------------------------------------------------------------------- reading


@click.command("firmware", context_settings=CLICK_CONTEXT_SETTINGS)
@device_options
@click.pass_context
def cli_firmware(
    ctx: click.Context, *, host: str | None, timeout: float | None, as_json: bool, as_json_bare: bool
) -> None:
    """Show the firmware version (FTP SYST; needs no login)."""

    def work(server: PrintServer) -> FirmwareReport:
        return FirmwareReport(host=server.endpoint.host, firmware=server.firmware_version())

    run_device_command(
        ctx,
        command=CommandName.FIRMWARE,
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=lambda report: f"{report.host}: firmware {report.firmware}",
    )


@click.command("device-info", context_settings=CLICK_CONTEXT_SETTINGS)
@device_options
@click.pass_context
def cli_device_info(
    ctx: click.Context, *, host: str | None, timeout: float | None, as_json: bool, as_json_bare: bool
) -> None:
    """Show the device's self-description (PSINF): names, MAC, firmware, addresses."""
    run_device_command(
        ctx,
        command=CommandName.DEVICE_INFO,
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=lambda server: server.info(),
        human=_render_info,
    )


def _render_info(info: DeviceInfo) -> str:
    lines = [
        f"Server name:   {info.server_name}",
        f"Default name:  {info.default_name}",
        f"MAC address:   {info.mac_address or 'unknown'}",
        f"Firmware:      {info.firmware_version}",
        f"Hardware ID:   {info.hardware_id}",
        f"IP address:    {info.ip_address or 'none'}",
        f"Subnet mask:   {info.subnet_mask or 'none'}",
        f"Gateway:       {info.gateway or 'none'}",
    ]
    return "\n".join(lines)


@click.command("status", context_settings=CLICK_CONTEXT_SETTINGS)
@device_options
@click.pass_context
def cli_status(
    ctx: click.Context, *, host: str | None, timeout: float | None, as_json: bool, as_json_bare: bool
) -> None:
    """Show each port's state and printer status (Telnet monitor)."""

    def work(server: PrintServer) -> StatusReport:
        return StatusReport(host=server.endpoint.host, ports=server.status())

    run_device_command(
        ctx,
        command=CommandName.STATUS,
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=_render_status,
    )


@click.command("check", context_settings=CLICK_CONTEXT_SETTINGS)
@option(
    "--reset",
    is_flag=True,
    default=False,
    help="Restart the device if a port is wedged, then check again (needs --yes).",
)
@option("--yes", is_flag=True, default=False, help="Confirm the restart --reset may make.")
@device_options
@click.pass_context
def cli_check(
    ctx: click.Context,
    *,
    reset: bool,
    yes: bool,
    host: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Find wedged ports: busy with no client, curable only by a restart. Exit 3 on a wedge.

    A port reading Printing / Direct Socket / 0 bytes serviced gets a bare connect (no data) to
    each RAW port routed there: a wedged port accepts it, a port another client holds refuses.
    """

    def work(server: PrintServer) -> CheckReport:
        if reset and not yes:
            raise ConfirmationRequiredError("check --reset restarts the device when a port is wedged; pass --yes")
        result = server.reset_if_wedged() if reset else server.check()
        return CheckReport(
            host=server.endpoint.host, ports=result.ports, restarted=result.restarted, before=result.before
        )

    run_device_command(
        ctx,
        command=CommandName.CHECK,
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=_render_check,
        outcome=lambda report: ExitCode.PORT_WEDGED if report.wedged else ExitCode.SUCCESS,
    )


def _render_check(report: CheckReport) -> str:
    lines: list[str] = []
    if report.restarted:
        lines.append(f"Restarted {report.host}: {_wedged_ports(report.before)} were wedged. Checked again:")
    lines.append(f"{'Port':<5} {'State':<9} {'Verdict':<20} Probed")
    for health in report.ports:
        verdict = "printing (unprobed)" if health.verdict is PortVerdict.UNPROBED else health.verdict.value
        probed = ", ".join(str(port) for port in health.probed) or "-"
        lines.append(f"{health.status.port.value:<5} {health.status.state.value:<9} {verdict:<20} {probed}")
    if report.wedged:
        advice = "a restart did not clear it" if report.restarted else "`check --reset --yes` restarts the device"
        lines.append(f"Wedged: {_wedged_ports(report.ports)}; {advice}.")
    return "\n".join(lines)


def _wedged_ports(ports: tuple[PortHealth, ...]) -> str:
    return ", ".join(health.status.port.value for health in ports if health.verdict is PortVerdict.WEDGED)


def _render_status(report: StatusReport) -> str:
    lines = [f"{'Port':<5} {'Type':<9} {'State':<9} {'Printer':<13} Held by"]
    for port in report.ports:
        held = port.occupied_by or "-"
        lines.append(
            f"{port.port.value:<5} {port.type.value:<9} {port.state.value:<9} {port.printer_status.value:<13} {held}"
        )
    return "\n".join(lines)


@click.command("queue", context_settings=CLICK_CONTEXT_SETTINGS)
@argument("queue", default="L1")
@option("--long", "long_format", is_flag=True, default=False, help="Ask for the long LPD queue listing.")
@device_options
@click.pass_context
def cli_queue(
    ctx: click.Context,
    queue: str,
    *,
    long_format: bool,
    host: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Show the LPD queue state of QUEUE (L1..L8). Read-only: it sends no print data."""

    def work(server: PrintServer) -> QueueReport:
        return QueueReport(
            host=server.endpoint.host, queue=queue, state=server.queue_state(queue, long_format=long_format)
        )

    run_device_command(
        ctx,
        command=CommandName.QUEUE,
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=lambda report: report.state.rstrip("\n"),
    )


# ---------------------------------------------------------------------- actions


_YES = option("--yes", is_flag=True, default=False, help="Confirm that the device should be changed.")
_CONFIRM_NAME = option(
    "--confirm-name",
    type=str,
    default="",
    help="The device's name (server or default name), repeated as confirmation.",
)


@click.command("reset", context_settings=CLICK_CONTEXT_SETTINGS)
@_YES
@option("--no-wait", "no_wait", is_flag=True, default=False, help="Return at once instead of waiting for the restart.")
@device_options
@click.pass_context
def cli_reset(
    ctx: click.Context,
    *,
    yes: bool,
    no_wait: bool,
    host: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Restart the print server and wait until it answers again; a stored configuration takes effect."""

    def work(server: PrintServer) -> ActionReport:
        _require_yes(yes, what=CommandName.RESET)
        server.reset(wait=not no_wait)
        return ActionReport(host=server.endpoint.host, action=CommandName.RESET, done=True)

    run_device_command(
        ctx,
        command=CommandName.RESET,
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=_render_action,
    )


@click.command("factory-default", context_settings=CLICK_CONTEXT_SETTINGS)
@_YES
@_CONFIRM_NAME
@device_options
@click.pass_context
def cli_factory_default(
    ctx: click.Context,
    *,
    yes: bool,
    confirm_name: str,
    host: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Restore factory settings: stored IP 0.0.0.0 with DHCP on, an empty name, no password.

    The device restarts and asks DHCP for an address; without a DHCP server, reach it with arp.
    """

    def work(server: PrintServer) -> ActionReport:
        _require_yes(yes, what=CommandName.FACTORY_DEFAULT)
        server.factory_default(confirm_name=confirm_name)
        return ActionReport(host=server.endpoint.host, action=CommandName.FACTORY_DEFAULT, done=True)

    run_device_command(
        ctx,
        command=CommandName.FACTORY_DEFAULT,
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=_render_action,
    )


@click.command("store-ip", context_settings=CLICK_CONTEXT_SETTINGS)
@_YES
@_CONFIRM_NAME
@device_options
@click.pass_context
def cli_store_ip(
    ctx: click.Context,
    *,
    yes: bool,
    confirm_name: str,
    host: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Store the address the device answers on now as its static IP (SETIP)."""

    def work(server: PrintServer) -> ActionReport:
        _require_yes(yes, what=CommandName.STORE_IP)
        server.store_ip(confirm_name=confirm_name)
        return ActionReport(host=server.endpoint.host, action=CommandName.STORE_IP, done=True)

    run_device_command(
        ctx,
        command=CommandName.STORE_IP,
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=_render_action,
    )


@click.group("password", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_password() -> None:
    """Set or clear the device's login password."""


@cli_password.command("set", context_settings=CLICK_CONTEXT_SETTINGS)
@option(
    "--from-file",
    "from_file",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    default=None,
    help="Read the new password from the first line of this file (else from a hidden prompt).",
)
@_YES
@device_options
@click.pass_context
def cli_password_set(
    ctx: click.Context,
    *,
    from_file: Path | None,
    yes: bool,
    host: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Set a new login password (at most 19 characters). Never pass it on the command line."""

    def work(server: PrintServer) -> ActionReport:
        _require_yes(yes, what=CommandName.CREDENTIAL_SET)
        server.set_password(_new_password(from_file))
        return ActionReport(host=server.endpoint.host, action=CommandName.CREDENTIAL_SET, done=True)

    run_device_command(
        ctx,
        command=CommandName.CREDENTIAL_SET,
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=_render_action,
    )


@cli_password.command("clear", context_settings=CLICK_CONTEXT_SETTINGS)
@_YES
@_CONFIRM_NAME
@device_options
@click.pass_context
def cli_password_clear(
    ctx: click.Context,
    *,
    yes: bool,
    confirm_name: str,
    host: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Clear the login password (PASSRESET)."""

    def work(server: PrintServer) -> ActionReport:
        _require_yes(yes, what=CommandName.CREDENTIAL_CLEAR)
        server.clear_password(confirm_name=confirm_name)
        return ActionReport(host=server.endpoint.host, action=CommandName.CREDENTIAL_CLEAR, done=True)

    run_device_command(
        ctx,
        command=CommandName.CREDENTIAL_CLEAR,
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=_render_action,
    )


def _new_password(from_file: Path | None) -> SecretStr:
    if from_file is not None:
        # Only the first line is the password, so only it is read: a file given by mistake (a
        # print job, a log) is not pulled into memory whole. Text mode maps \r\n and \r to \n.
        with from_file.open(encoding="utf-8") as source:
            return SecretStr(source.readline().rstrip("\n"))
    if not sys.stdin.isatty():
        raise ValueError("no terminal to ask for the new password; use --from-file")
    entered: str = click.prompt("New password", hide_input=True, confirmation_prompt=True, err=True)
    return SecretStr(entered)


def _render_action(report: ActionReport) -> str:
    return f"{report.host}: {report.action.value} done"


__all__ = [
    "ActionReport",
    "CheckReport",
    "FirmwareReport",
    "QueueReport",
    "StatusReport",
    "cli_check",
    "cli_device_info",
    "cli_factory_default",
    "cli_firmware",
    "cli_password",
    "cli_queue",
    "cli_reset",
    "cli_status",
    "cli_store_ip",
]
