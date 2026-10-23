"""``device-config``: read, change, export and import the print server's CONFIG.

Changing works on the typed model: every value is validated before anything is sent, the
command shows exactly which parameters change, and nothing is written without ``--yes``. After
writing, the device is restarted so the configuration takes effect (``--no-apply`` skips that).
The app's own settings are the separate ``config`` command.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import rich_click as click
from pydantic import BaseModel

from sercomm_printserver.domain.config_codec import ConfigChange, find_line, parse_config, with_value
from sercomm_printserver.domain.config_model import DeviceConfig
from sercomm_printserver.domain.errors import ConfirmationRequiredError

from ..constants import CLICK_CONTEXT_SETTINGS
from ..typed_click import argument, option
from ._device import DeviceFlags, device_options, run_device_command

if TYPE_CHECKING:
    from sercomm_printserver.application.print_server import PrintServer


class ConfigReport(BaseModel, frozen=True):
    """Answer of ``device-config show``."""

    host: str
    config: DeviceConfig
    text: str


class ParameterReport(BaseModel, frozen=True):
    """Answer of ``device-config get``."""

    host: str
    number: int
    token: str
    value: str


class ChangeReport(BaseModel, frozen=True):
    """Answer of ``device-config set`` and ``import``."""

    host: str
    changes: tuple[ConfigChange, ...]
    written: bool
    applied: bool


class ExportReport(BaseModel, frozen=True):
    """Answer of ``device-config export``."""

    host: str
    path: str
    size: int


def _flags(host: str | None, timeout: float | None, as_json: bool, as_json_bare: bool) -> DeviceFlags:
    return DeviceFlags(host=host, timeout=timeout, as_json=as_json, as_json_bare=as_json_bare)


@click.group("device-config", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_device_config() -> None:
    """Read and change the print server's configuration (CONFIG)."""


@cli_device_config.command("show", context_settings=CLICK_CONTEXT_SETTINGS)
@device_options
@click.pass_context
def cli_device_config_show(
    ctx: click.Context, *, host: str | None, timeout: float | None, as_json: bool, as_json_bare: bool
) -> None:
    """Show the whole configuration."""

    def work(server: PrintServer) -> ConfigReport:
        text = server.read_config_text()
        return ConfigReport(host=server.endpoint.host, config=parse_config(text), text=text)

    run_device_command(
        ctx,
        command="device-config show",
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=lambda report: report.text.rstrip("\n"),
    )


@cli_device_config.command("get", context_settings=CLICK_CONTEXT_SETTINGS)
@argument("key")
@device_options
@click.pass_context
def cli_device_config_get(
    ctx: click.Context, key: str, *, host: str | None, timeout: float | None, as_json: bool, as_json_bare: bool
) -> None:
    """Show one parameter, named by token (IP_ADDR) or line number (4000)."""

    def work(server: PrintServer) -> ParameterReport:
        line = find_line(server.read_config(), key)
        return ParameterReport(
            host=server.endpoint.host, number=line.number, token=line.token.strip(), value=line.value
        )

    run_device_command(
        ctx,
        command="device-config get",
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=lambda report: report.value,
    )


_YES = option("--yes", is_flag=True, default=False, help="Write the change to the device.")
_NO_APPLY = option(
    "--no-apply", "no_apply", is_flag=True, default=False, help="Do not restart the device after writing."
)


@cli_device_config.command("set", context_settings=CLICK_CONTEXT_SETTINGS)
@argument("assignments", nargs=-1, required=True, metavar="KEY=VALUE...")
@_YES
@_NO_APPLY
@device_options
@click.pass_context
def cli_device_config_set(
    ctx: click.Context,
    assignments: tuple[str, ...],
    *,
    yes: bool,
    no_apply: bool,
    host: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Change parameters, e.g. CONTACT="printer room" DHCP_MODE=Disable. Shows the diff; writes with --yes."""

    def work(server: PrintServer) -> ChangeReport:
        new = server.read_config()
        for assignment in assignments:
            key, separator, value = assignment.partition("=")
            if not separator:
                raise ValueError(f"expected KEY=VALUE, got {assignment!r}")
            new = with_value(new, key, value)
        return _write(server, new, yes=yes, apply=not no_apply)

    run_device_command(
        ctx, command="device-config set", flags=_flags(host, timeout, as_json, as_json_bare), work=work, human=_render
    )


@cli_device_config.command("export", context_settings=CLICK_CONTEXT_SETTINGS)
@argument("path", type=click.Path(dir_okay=False, writable=True, readable=False, path_type=Path))
@device_options
@click.pass_context
def cli_device_config_export(
    ctx: click.Context, path: Path, *, host: str | None, timeout: float | None, as_json: bool, as_json_bare: bool
) -> None:
    """Save the CONFIG file exactly as the device sends it."""

    def work(server: PrintServer) -> ExportReport:
        data = server.read_config_text().encode("ascii")
        path.write_bytes(data)
        return ExportReport(host=server.endpoint.host, path=str(path), size=len(data))

    run_device_command(
        ctx,
        command="device-config export",
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=lambda report: f"{report.host}: wrote {report.size} bytes to {report.path}",
    )


@cli_device_config.command("import", context_settings=CLICK_CONTEXT_SETTINGS)
@argument("path", type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path))
@_YES
@_NO_APPLY
@device_options
@click.pass_context
def cli_device_config_import(
    ctx: click.Context,
    path: Path,
    *,
    yes: bool,
    no_apply: bool,
    host: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Write a CONFIG file (as exported) to the device. Shows the diff; writes with --yes."""

    def work(server: PrintServer) -> ChangeReport:
        new = parse_config(path.read_text(encoding="ascii"))
        return _write(server, new, yes=yes, apply=not no_apply)

    run_device_command(
        ctx,
        command="device-config import",
        flags=_flags(host, timeout, as_json, as_json_bare),
        work=work,
        human=_render,
    )


def _write(server: PrintServer, new: DeviceConfig, *, yes: bool, apply: bool) -> ChangeReport:
    if not yes:
        changes = server.plan_config(new)
        listing = "; ".join(f"{change.token}: {change.old!r} -> {change.new!r}" for change in changes)
        raise ConfirmationRequiredError(f"not written, pass --yes to write: {listing or 'no change'}")
    result = server.write_config(new, apply=apply)
    return ChangeReport(
        host=server.endpoint.host, changes=result.changes, written=result.written, applied=result.applied
    )


def _render(report: ChangeReport) -> str:
    if not report.written:
        return f"{report.host}: nothing to change"
    lines = [f"{change.token}: {change.old!r} -> {change.new!r}" for change in report.changes]
    lines.append(f"{report.host}: written{', device restarted' if report.applied else ''}")
    return "\n".join(lines)


__all__ = [
    "ChangeReport",
    "ConfigReport",
    "ExportReport",
    "ParameterReport",
    "cli_device_config",
]
