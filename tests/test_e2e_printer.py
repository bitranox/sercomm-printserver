"""End-to-end print tests: real jobs through the test print server to a real printer.

Run with ``SERCOMM_E2E=1 SERCOMM_E2E_PRINTER=1 pytest -m printer tests/test_e2e_printer.py`` once
``test-device.json`` names the printer in its ``printer`` section. Each job prints one short
label whose text says which test sent it and when, so the paper can be matched to the run.

What makes these tests different from the RAW and LPD tests in ``test_e2e_device.py``: there,
no printer takes the data, so a job stays on its port until a restart clears it, and an LPD
submit times out waiting for the device to acknowledge the data file. Here the printer takes
the data, so the LPD submit is acknowledged and the port drains back to idle with no restart.
That difference is what each test asserts. None of them changes the configuration.

The device answers one RAW connection at a time and refuses a new one for about 1-2 s after the
previous close (measured on a PS301, FW 6022); nothing else may use the printer during the run.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from enum import Enum
from ipaddress import IPv4Address
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel, ConfigDict, Field

from sercomm_printserver.composition import open_print_server
from sercomm_printserver.domain.config_codec import find_line, parse_config
from sercomm_printserver.domain.endpoint import DeviceEndpoint, PrintJob
from sercomm_printserver.domain.port_status import PortState, PrinterStatus

if TYPE_CHECKING:
    from sercomm_printserver.application.print_server import PrintServer

pytestmark = [pytest.mark.device, pytest.mark.printer]

_ROOT = Path(__file__).resolve().parents[1]
#: How long a job may take to drain to an idle port. A one-line label is under 100 bytes, a
#: fraction of a second even on a 9600-baud serial port; the margin covers the printer itself.
_DRAIN_SECONDS = 30.0
#: Pause between status reads while waiting; each read is an FTP session of its own.
_POLL_SECONDS = 1.0


class LabelFormat(Enum):
    """How a test label is encoded for the printer."""

    TEXT = "text"
    DPL = "dpl"


class _Printer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_printer: int = Field(ge=1, le=3)
    port: str
    label: LabelFormat


class _PrinterDevice(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    host: IPv4Address
    printer: _Printer | None = None


@pytest.fixture(scope="module")
def printer_device() -> _PrinterDevice:
    device = _PrinterDevice.model_validate(json.loads((_ROOT / "test-device.json").read_text(encoding="utf-8")))
    if device.printer is None:
        pytest.skip("test-device.json has no printer section")
    return device


@pytest.fixture(scope="module")
def printer(printer_device: _PrinterDevice) -> _Printer:
    assert printer_device.printer is not None
    return printer_device.printer


@pytest.fixture(scope="module")
def server(printer_device: _PrinterDevice) -> PrintServer:
    return open_print_server(DeviceEndpoint(host=str(printer_device.host), timeout=10.0))


def _label(printer: _Printer, text: str) -> bytes:
    """One printed line saying who sent it and when."""
    line = f"{text} {datetime.now(tz=timezone.utc):%H:%M:%S}Z"
    if printer.label is LabelFormat.DPL:
        # <STX>n inches, <STX>L label format, one text record (font 1, 0.98 in up, 0.39 in in),
        # one copy, end of label.
        return b"\x02n\x02L\r1211000000980039" + line.encode("ascii") + b"\rQ0001\rE\r"
    return line.encode("ascii") + b"\r\n\x0c"


def _port_state(server: PrintServer, port: str) -> PortState:
    return next(status.state for status in server.status() if status.port.value == port)


def _wait_until_idle(server: PrintServer, port: str) -> bool:
    deadline = time.monotonic() + _DRAIN_SECONDS
    while time.monotonic() < deadline:
        if _port_state(server, port) is PortState.IDLE:
            return True
        time.sleep(_POLL_SECONDS)
    return False


def _require_idle_start(server: PrintServer, port: str) -> None:
    if _port_state(server, port) is not PortState.IDLE:
        pytest.skip(f"{port} is busy already; is something else printing?")


def test_the_printer_is_on_line_on_the_port_its_logical_printer_is_routed_to(
    server: PrintServer, printer: _Printer
) -> None:
    routed_to = find_line(parse_config(server.read_config_text()), f"L{printer.logical_printer}_PROUT").value
    status = next(status for status in server.status() if status.port.value == printer.port)

    assert routed_to == printer.port
    assert status.printer_status is PrinterStatus.ON_LINE


def test_two_raw_jobs_back_to_back_reach_the_printer_and_the_port_drains(
    server: PrintServer, printer: _Printer
) -> None:
    # The second connect meets the device's 1-2 s refusal after the first job's close; the RAW
    # adapter's retry is what lets it through.
    _require_idle_start(server, printer.port)
    drained = False
    try:
        server.print_raw(printer.logical_printer, _label(printer, "E2E RAW 1/2"))
        server.print_raw(printer.logical_printer, _label(printer, "E2E RAW 2/2"))
        drained = _wait_until_idle(server, printer.port)
    finally:
        if not drained:
            server.reset(wait=True)

    assert drained, f"{printer.port} still busy {_DRAIN_SECONDS:.0f} s after the jobs"


def test_an_lpd_job_is_acknowledged_and_the_port_drains(server: PrintServer, printer: _Printer) -> None:
    # Without a printer the device holds back its acknowledgement of the data file and the
    # submit times out (test_e2e_device.py); a printer that takes the data lets it complete.
    _require_idle_start(server, printer.port)
    drained = False
    try:
        server.print_lpd(
            f"L{printer.logical_printer}", PrintJob(data=_label(printer, "E2E LPD"), name="sercomm-e2e-lpd")
        )
        drained = _wait_until_idle(server, printer.port)
    finally:
        if not drained:
            server.reset(wait=True)

    assert drained, f"{printer.port} still busy {_DRAIN_SECONDS:.0f} s after the job"
