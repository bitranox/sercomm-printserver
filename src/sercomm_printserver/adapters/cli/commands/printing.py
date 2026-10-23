"""``print``: send a file to a logical printer by LPD or RAW.

LPD names the logical printer by queue (``L1``..``L8``); RAW sends to its direct-socket port.
The device prints the data as it arrives and applies no options, so the file must already be in
the printer's language (PCL, PostScript, plain text).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO

import rich_click as click
from pydantic import BaseModel

from sercomm_printserver.domain.endpoint import PrintJob

from ..constants import CLICK_CONTEXT_SETTINGS
from ..typed_click import argument, option
from ._device import DeviceFlags, device_options, run_device_command

if TYPE_CHECKING:
    from sercomm_printserver.application.print_server import PrintServer


class PrintReport(BaseModel, frozen=True):
    """Answer of ``print lpd`` and ``print raw``."""

    host: str
    target: str
    size: int


def _flags(host: str | None, timeout: float | None, as_json: bool, as_json_bare: bool) -> DeviceFlags:
    return DeviceFlags(host=host, timeout=timeout, as_json=as_json, as_json_bare=as_json_bare)


def _render(report: PrintReport) -> str:
    return f"{report.host}: sent {report.size} bytes to {report.target}"


@click.group("print", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_print() -> None:
    """Send print data to a logical printer."""


@cli_print.command("lpd", context_settings=CLICK_CONTEXT_SETTINGS)
@argument("queue")
@argument("source", type=click.File("rb"))
@option("--job-name", type=str, default="job", help="Job name in the LPD control file.")
@device_options
@click.pass_context
def cli_print_lpd(
    ctx: click.Context,
    queue: str,
    source: BinaryIO,
    *,
    job_name: str,
    host: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Send SOURCE (a file, or - for stdin) to LPD queue QUEUE (L1..L8)."""

    def work(server: PrintServer) -> PrintReport:
        job = PrintJob(data=source.read(), name=job_name)
        server.print_lpd(queue, job)
        return PrintReport(host=server.endpoint.host, target=f"LPD queue {queue}", size=len(job.data))

    run_device_command(
        ctx, command="print lpd", flags=_flags(host, timeout, as_json, as_json_bare), work=work, human=_render
    )


@cli_print.command("raw", context_settings=CLICK_CONTEXT_SETTINGS)
@argument("printer", type=click.IntRange(min=1, max=8))
@argument("source", type=click.File("rb"))
@device_options
@click.pass_context
def cli_print_raw(
    ctx: click.Context,
    printer: int,
    source: BinaryIO,
    *,
    host: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Send SOURCE (a file, or - for stdin) to the RAW port of logical printer PRINTER (1..8)."""

    def work(server: PrintServer) -> PrintReport:
        data = source.read()
        server.print_raw(printer, data)
        return PrintReport(host=server.endpoint.host, target=f"RAW port of L{printer}", size=len(data))

    run_device_command(
        ctx, command="print raw", flags=_flags(host, timeout, as_json, as_json_bare), work=work, human=_render
    )


__all__ = ["PrintReport", "cli_print"]
