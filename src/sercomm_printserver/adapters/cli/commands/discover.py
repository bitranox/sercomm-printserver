"""``discover``: find the family's print servers on the network by their FTP greeting."""

from __future__ import annotations

from ipaddress import IPv4Network

import lib_log_rich.runtime
import rich_click as click

from sercomm_printserver.application.discovery import DiscoveryReport, discover

from .. import safe_console
from ..constants import CLICK_CONTEXT_SETTINGS, CommandName
from ..context import get_cli_context
from ..envelope import Envelope, OutputMode, report_failure, write_envelope
from ..typed_click import option
from ._device import exit_code_for

#: While a sweep has dozens of connects in flight, a present host's TCP connect can take over
#: 2 s; with 1 s per host a /24 sweep missed devices that 3 s finds.
_DEFAULT_TIMEOUT = 3.0


@click.command("discover", context_settings=CLICK_CONTEXT_SETTINGS)
@option(
    "--network",
    "networks",
    multiple=True,
    metavar="CIDR",
    help="Network to search, e.g. 192.0.2.0/24 (repeatable; default: this host's networks).",
)
@option(
    "--timeout",
    type=click.FloatRange(min=0.1, max=60),
    default=_DEFAULT_TIMEOUT,
    show_default=True,
    help="Seconds to wait for each host's greeting. Under a sweep a present host can need 2 s.",
)
@option("--json", "as_json", is_flag=True, default=False, help="Answer as an indented JSON envelope.")
@option("--json-bare", "as_json_bare", is_flag=True, default=False, help="Answer as one-line JSON.")
@click.pass_context
def cli_discover(
    ctx: click.Context, *, networks: tuple[str, ...], timeout: float, as_json: bool, as_json_bare: bool
) -> None:
    """Find print servers: every host answering FTP with "220 Print Server Ready."."""
    mode = OutputMode.of(as_json=as_json, as_json_bare=as_json_bare)
    scanner = get_cli_context(ctx).services.host_scanner
    with lib_log_rich.runtime.bind(
        job_id=f"cli-{CommandName.DISCOVER.value}", extra={"command": CommandName.DISCOVER.value}
    ):
        try:
            chosen = [IPv4Network(network, strict=False) for network in networks]
            report = discover(scanner, networks=chosen or None, timeout=timeout)
        except ValueError as error:
            report_failure(error, command=CommandName.DISCOVER, mode=mode)
            ctx.exit(exit_code_for(error))
    if mode.machine:
        write_envelope(
            Envelope.of(command=CommandName.DISCOVER, payload=report, skipped=list(report.skipped)), mode=mode
        )
        return
    safe_console.echo(_render(report))
    for note in report.skipped:
        safe_console.echo(f"skipped {note}", err=True)


def _render(report: DiscoveryReport) -> str:
    searched = ", ".join(str(network) for network in report.networks) or "nothing"
    lines = [f"Searched {searched} ({report.probed} addresses): {len(report.devices)} print server(s)"]
    lines += [f"{device.host!s:<16} MAC {device.mac_address or 'unknown'}" for device in report.devices]
    return "\n".join(lines)


__all__ = ["cli_discover"]
