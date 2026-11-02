"""``print``: send a file to a logical printer by LPD or RAW.

LPD names the logical printer by queue (``L1``..``L8``); RAW sends to its direct-socket port.
The device prints the data as it arrives and applies no options, so the file must already be in
the printer's language (PCL, PostScript, plain text).
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, BinaryIO

import rich_click as click
from pydantic import BaseModel, model_validator

from sercomm_printserver.application.print_server import DEFAULT_VERIFY_TIMEOUT
from sercomm_printserver.domain.config_types import PortId
from sercomm_printserver.domain.endpoint import PrintJob

from ..constants import CLICK_CONTEXT_SETTINGS, CommandName
from ..typed_click import argument, option
from ._device import DeviceFlags, device_options, run_device_command

if TYPE_CHECKING:
    from sercomm_printserver.application.print_server import PrintServer


class PrintTransport(str, Enum):
    """How the data reached the logical printer."""

    LPD = "lpd"
    RAW = "raw"


class PrintReport(BaseModel, frozen=True):
    """Answer of ``print lpd`` and ``print raw``.

    LPD names its target by ``queue`` and RAW by ``printer``; the other one is None, so a script
    reads the target without parsing a sentence. Queue names stay free strings: the device
    defines them, and this tool does not claim to know every model's set.

    Example:
        >>> report = PrintReport(host="192.0.2.52", transport=PrintTransport.RAW, queue=None, printer=1, size=2)
        >>> report.model_dump_json()
        '{"host":"192.0.2.52","transport":"raw","queue":null,"printer":1,"size":2}'
    """

    host: str
    transport: PrintTransport
    queue: str | None
    printer: int | None
    size: int

    @model_validator(mode="after")
    def _names_its_target_by_its_transport(self) -> PrintReport:
        named_by_queue = self.transport is PrintTransport.LPD
        if (self.queue is not None) != named_by_queue or (self.printer is not None) == named_by_queue:
            raise ValueError(f"a {self.transport.value} print names its target by exactly one of queue/printer")
        return self


class VerifiedPrintReport(PrintReport, frozen=True):
    """Answer of ``print raw --verify``: the port the job went to reads idle again.

    Example:
        >>> report = VerifiedPrintReport(
        ...     host="192.0.2.52", transport=PrintTransport.RAW, queue=None, printer=3, size=2, idle_port=PortId.SP
        ... )
        >>> report.model_dump_json()
        '{"host":"192.0.2.52","transport":"raw","queue":null,"printer":3,"size":2,"idle_port":"SP"}'
    """

    idle_port: PortId


def _flags(host: str | None, timeout: float | None, as_json: bool, as_json_bare: bool) -> DeviceFlags:
    return DeviceFlags(host=host, timeout=timeout, as_json=as_json, as_json_bare=as_json_bare)


def _render(report: PrintReport) -> str:
    if report.transport is PrintTransport.LPD:
        target = f"{report.transport.value.upper()} queue {report.queue}"
    else:
        target = f"{report.transport.value.upper()} port of L{report.printer}"
    sent = f"{report.host}: sent {report.size} bytes to {target}"
    return f"{sent}; {report.idle_port.value} is Idle again" if isinstance(report, VerifiedPrintReport) else sent


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
        return PrintReport(
            host=server.endpoint.host, transport=PrintTransport.LPD, queue=queue, printer=None, size=len(job.data)
        )

    run_device_command(
        ctx, command=CommandName.PRINT_LPD, flags=_flags(host, timeout, as_json, as_json_bare), work=work, human=_render
    )


@cli_print.command("raw", context_settings=CLICK_CONTEXT_SETTINGS)
@argument("printer", type=click.IntRange(min=1, max=3))
@argument("source", type=click.File("rb"))
@option(
    "--verify",
    is_flag=True,
    default=False,
    help="Wait for the routed port to read Idle before sending, and again after. Idle means the port is free, "
    "not that a page came out. Busy before the send exits 75, nothing sent; busy after it exits 110, data sent.",
)
@option(
    "--verify-timeout",
    type=click.FloatRange(min=0.1, max=3600),
    default=None,
    help=f"Seconds each --verify wait may take, before and after the send (default {DEFAULT_VERIFY_TIMEOUT:g}).",
)
@device_options
@click.pass_context
def cli_print_raw(
    ctx: click.Context,
    printer: int,
    source: BinaryIO,
    *,
    verify: bool,
    verify_timeout: float | None,
    host: str | None,
    timeout: float | None,
    as_json: bool,
    as_json_bare: bool,
) -> None:
    """Send SOURCE (a file, or - for stdin) to the RAW port of logical printer PRINTER (1..3)."""
    if verify_timeout is not None and not verify:
        # Taking the value and not watching would read as a verified print that was never verified.
        raise click.UsageError("--verify-timeout needs --verify")

    def work(server: PrintServer) -> PrintReport:
        data = source.read()
        fields = PrintReport(
            host=server.endpoint.host, transport=PrintTransport.RAW, queue=None, printer=printer, size=len(data)
        )
        if not verify:
            server.print_raw(printer, data)
            return fields
        status = server.print_raw_verified(printer, data, timeout=verify_timeout or DEFAULT_VERIFY_TIMEOUT)
        return VerifiedPrintReport(**fields.model_dump(), idle_port=status.port)

    run_device_command(
        ctx, command=CommandName.PRINT_RAW, flags=_flags(host, timeout, as_json, as_json_bare), work=work, human=_render
    )


__all__ = ["PrintReport", "PrintTransport", "VerifiedPrintReport", "cli_print"]
