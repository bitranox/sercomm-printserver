"""``print raw`` exit codes when the connection breaks: 69 only while nothing was sent.

A script may resend a job on exit 69 (``DeviceUnavailableError``), so a connection that breaks
after the device took data must exit with another code: this device prints data as it arrives,
and a resend would print the job twice. The RAW port is a real loopback socket here, so the
failure comes from the real adapter, not from a fake that raises what the test expects.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fake_lpd_server import closed_port
from fake_raw_server import FakeRawServer, RawBehaviour

from sercomm_printserver.adapters.cli import root as cli_root
from sercomm_printserver.adapters.memory.device import FakeDevice, FakeTftp
from sercomm_printserver.adapters.raw import RawPrinter
from sercomm_printserver.application.print_server import DevicePorts, PrintServer
from sercomm_printserver.composition import build_testing

if TYPE_CHECKING:
    from collections.abc import Callable

    from click.testing import CliRunner, Result

    from sercomm_printserver.composition import AppServices
    from sercomm_printserver.domain.endpoint import DeviceEndpoint

pytestmark = pytest.mark.os_agnostic

_DUMPS = Path(__file__).resolve().parents[1] / "docs" / "device-dump"
#: Logical printer 1 is routed to P1 in the dumped configuration: a parallel port, so no drain wait.
_PRINT_RAW = ["print", "raw", "1", "-", "--host", "127.0.0.1", "--timeout", "5", "--json-bare"]
#: More than the loopback buffers hold, so a reset after 1024 bytes meets a send.
_BIG_JOB = bytes(range(256)) * 1024 * 32
_IDLE_PORTS = (
    "(P1)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n\r\n"
    "(P2)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n\r\n"
    "(SP)STATE: Idle\r\nTYPE: Serial\r\nPRINTER STATUS: On-Line\r\n"
)


@pytest.fixture
def device() -> FakeDevice:
    return FakeDevice(
        config=(_DUMPS / "CONFIG.txt").read_text(encoding="ascii"),
        psinf=(_DUMPS / "PSINF.txt").read_text(encoding="ascii"),
        monitor=(_DUMPS / "telnet-monitor.txt").read_text(encoding="ascii"),
    )


def _services(device: FakeDevice, raw_port: int) -> Callable[[], AppServices]:
    """The in-memory device for configuration and status, a real ``RawPrinter`` on ``raw_port``."""

    def open_print_server(endpoint: DeviceEndpoint, *, raw_port_base: int) -> PrintServer:
        ports = DevicePorts(
            ftp=device, telnet=device, tftp=FakeTftp(device), lpd=device, raw=RawPrinter(), uptime=device
        )
        return PrintServer(endpoint, ports, raw_port_base=raw_port)

    return lambda: dataclasses.replace(build_testing(), open_print_server=open_print_server)


def _envelope(result: Result) -> dict[str, object]:
    document: dict[str, object] = json.loads(result.stdout)
    return document


def test_a_reset_after_the_device_took_data_exits_110_not_69(cli_runner: CliRunner, device: FakeDevice) -> None:
    with FakeRawServer(behaviour=RawBehaviour.RESET_MID_STREAM, reset_after=1024) as server:
        result = cli_runner.invoke(cli_root.cli, _PRINT_RAW, obj=_services(device, server.port), input=_BIG_JOB)

    assert len(server.received) >= 1024
    assert result.exit_code == 110, result.output
    assert _envelope(result)["error"] == "DeliveryUnconfirmedError"


def test_a_reset_after_the_whole_job_arrived_exits_110_not_69(cli_runner: CliRunner, device: FakeDevice) -> None:
    with FakeRawServer(behaviour=RawBehaviour.RESET_AT_EOF) as server:
        result = cli_runner.invoke(cli_root.cli, _PRINT_RAW, obj=_services(device, server.port), input=b"job")

    assert server.received == b"job"
    assert result.exit_code == 110, result.output
    assert _envelope(result)["error"] == "DeliveryUnconfirmedError"


def test_a_refused_connection_sends_nothing_and_exits_69(cli_runner: CliRunner, device: FakeDevice) -> None:
    result = cli_runner.invoke(cli_root.cli, _PRINT_RAW, obj=_services(device, closed_port()), input=b"job")

    assert result.exit_code == 69, result.output
    assert _envelope(result)["error"] == "DeviceUnavailableError"


def test_a_verified_print_whose_send_breaks_after_data_went_out_exits_110_not_69(
    cli_runner: CliRunner, device: FakeDevice
) -> None:
    device.monitor_text = _IDLE_PORTS  # the port is free before the send, so the send runs
    with FakeRawServer(behaviour=RawBehaviour.RESET_MID_STREAM, reset_after=1024) as server:
        result = cli_runner.invoke(
            cli_root.cli, [*_PRINT_RAW, "--verify"], obj=_services(device, server.port), input=_BIG_JOB
        )

    assert len(server.received) >= 1024
    assert result.exit_code == 110, result.output
    assert _envelope(result)["error"] == "DeliveryUnconfirmedError"
