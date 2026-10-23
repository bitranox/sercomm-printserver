"""Device commands end to end through the CLI, against the in-memory device.

The device stands behind every port, the CLI resolves it from ``--host`` (the in-memory
configuration has no ``[device]`` host), and each test reads what reached the device, not only
what was printed.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sercomm_printserver.adapters.cli import root as cli_root
from sercomm_printserver.adapters.memory.device import FakeDevice, FakeTftp
from sercomm_printserver.application.print_server import DevicePorts, PrintServer
from sercomm_printserver.composition import build_testing
from sercomm_printserver.domain.device_files import DeviceAction

if TYPE_CHECKING:
    from collections.abc import Callable

    from click.testing import CliRunner

    from sercomm_printserver.composition import AppServices
    from sercomm_printserver.domain.endpoint import DeviceEndpoint

_DUMPS = Path(__file__).resolve().parents[1] / "docs" / "device-dump"
_HOST = ["--host", "192.0.2.52"]


@pytest.fixture
def device() -> FakeDevice:
    return FakeDevice(
        config=(_DUMPS / "CONFIG.txt").read_text(encoding="ascii"),
        psinf=(_DUMPS / "PSINF.txt").read_text(encoding="ascii"),
        monitor=(_DUMPS / "telnet-monitor.txt").read_text(encoding="ascii"),
    )


@pytest.fixture
def services(device: FakeDevice) -> Callable[[], AppServices]:
    def open_print_server(endpoint: DeviceEndpoint, *, raw_port_base: int) -> PrintServer:
        ports = DevicePorts(ftp=device, telnet=device, tftp=FakeTftp(device), lpd=device, raw=device, uptime=device)
        return PrintServer(endpoint, ports, raw_port_base=raw_port_base)

    return lambda: dataclasses.replace(build_testing(), open_print_server=open_print_server)


def _json(output: str) -> dict[str, object]:
    document: dict[str, object] = json.loads(output)
    return document


# ---------------------------------------------------------------- reading


def test_firmware_answers_for_a_person_and_as_an_envelope(
    cli_runner: CliRunner, services: Callable[[], AppServices]
) -> None:
    human = cli_runner.invoke(cli_root.cli, ["firmware", *_HOST], obj=services)
    machine = cli_runner.invoke(cli_root.cli, ["firmware", *_HOST, "--json-bare"], obj=services)

    assert human.exit_code == 0
    assert human.output.strip() == "192.0.2.52: firmware 6022"
    assert _json(machine.output) == {
        "ok": True,
        "command": "firmware",
        "data": {"host": "192.0.2.52", "firmware": "6022"},
        "skipped": [],
    }


def test_device_info_envelope_carries_the_typed_report(
    cli_runner: CliRunner, services: Callable[[], AppServices]
) -> None:
    result = cli_runner.invoke(cli_root.cli, ["device-info", *_HOST, "--json"], obj=services)

    data = _json(result.output)["data"]
    assert isinstance(data, dict)
    assert (data["server_name"], data["mac_address"], data["ip_address"]) == (
        "PS_EXAMPLE",
        "00:c0:02:12:34:56",
        "192.0.2.52",
    )


def test_status_lists_every_port(cli_runner: CliRunner, services: Callable[[], AppServices]) -> None:
    result = cli_runner.invoke(cli_root.cli, ["status", *_HOST], obj=services)

    assert result.exit_code == 0
    assert [line.split()[0] for line in result.output.splitlines()] == ["Port", "P1", "P2", "SP"]
    assert "Direct Socket" in result.output


def test_device_config_get_reads_one_parameter(cli_runner: CliRunner, services: Callable[[], AppServices]) -> None:
    result = cli_runner.invoke(cli_root.cli, ["device-config", "get", "MASK", *_HOST], obj=services)

    assert (result.exit_code, result.output) == (0, "255.255.255.0\n")


def test_device_config_export_writes_the_exact_device_file(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice, tmp_path: Path
) -> None:
    target = tmp_path / "CONFIG.txt"

    result = cli_runner.invoke(cli_root.cli, ["device-config", "export", str(target), *_HOST], obj=services)

    assert result.exit_code == 0
    assert target.read_bytes() == device.config.encode("ascii")


# ---------------------------------------------------------------- refusals and their exit codes


def test_no_host_anywhere_exits_78(cli_runner: CliRunner, services: Callable[[], AppServices]) -> None:
    result = cli_runner.invoke(cli_root.cli, ["firmware", "--json-bare"], obj=services)

    assert result.exit_code == 78
    assert _json(result.output)["error"] == "ConfigurationError"


def test_an_unreachable_device_exits_69(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    device.reachable = False

    result = cli_runner.invoke(cli_root.cli, ["status", *_HOST], obj=services)

    assert result.exit_code == 69
    assert "does not answer" in result.output


def test_a_change_without_yes_shows_the_plan_writes_nothing_and_exits_77(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    before = device.config

    result = cli_runner.invoke(cli_root.cli, ["device-config", "set", "CONTACT=lab", *_HOST], obj=services)

    assert result.exit_code == 77
    assert "CONTACT: '' -> 'lab'" in result.output
    assert device.config == before
    assert device.actions == []


def test_a_change_with_yes_is_written_and_applied(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    result = cli_runner.invoke(
        cli_root.cli, ["device-config", "set", "CONTACT=lab", "LOCATION=room 2", "--yes", *_HOST], obj=services
    )

    assert result.exit_code == 0
    assert "6000 CONTACT:lab\n" in device.config
    assert "6001 LOCATION:room 2\n" in device.config
    assert device.actions == [DeviceAction.RESET]


def test_an_invalid_value_exits_22_before_anything_is_sent(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    before = device.config

    result = cli_runner.invoke(
        cli_root.cli, ["device-config", "set", "IP_ADDR=300.1.1.1", "--yes", *_HOST, "--json-bare"], obj=services
    )

    assert result.exit_code == 22
    assert _json(result.output)["error"] == "ConfigFormatError"
    assert device.config == before


def test_reset_without_yes_exits_77(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    result = cli_runner.invoke(cli_root.cli, ["reset", *_HOST], obj=services)

    assert result.exit_code == 77
    assert device.actions == []


@pytest.mark.parametrize(
    ("args", "action"),
    [
        (["factory-default"], DeviceAction.FACTORY_DEFAULT),
        (["store-ip"], DeviceAction.STORE_IP),
        (["password", "clear"], DeviceAction.CREDENTIAL_RESET),
    ],
)
def test_a_dangerous_action_needs_yes_and_the_device_name(
    cli_runner: CliRunner,
    services: Callable[[], AppServices],
    device: FakeDevice,
    args: list[str],
    action: DeviceAction,
) -> None:
    only_yes = cli_runner.invoke(cli_root.cli, [*args, "--yes", *_HOST], obj=services)
    wrong_name = cli_runner.invoke(cli_root.cli, [*args, "--yes", "--confirm-name", "OTHER", *_HOST], obj=services)
    no_yes = cli_runner.invoke(cli_root.cli, [*args, "--confirm-name", "PS_EXAMPLE", *_HOST], obj=services)
    assert (only_yes.exit_code, wrong_name.exit_code, no_yes.exit_code) == (77, 77, 77)
    assert device.actions == []

    done = cli_runner.invoke(cli_root.cli, [*args, "--yes", "--confirm-name", "PS_EXAMPLE", *_HOST], obj=services)

    assert done.exit_code == 0
    assert device.actions == [action]


def test_password_set_reads_the_new_password_from_a_file(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice, tmp_path: Path
) -> None:
    secret_file = tmp_path / "pw.txt"
    secret_file.write_text("n3w-pass\n", encoding="utf-8")

    result = cli_runner.invoke(
        cli_root.cli, ["password", "set", "--from-file", str(secret_file), "--yes", *_HOST, "--json-bare"], obj=services
    )

    assert result.exit_code == 0
    assert device.credential == "n3w-pass"
    assert "n3w-pass" not in result.output


# ---------------------------------------------------------------- printing


def test_print_lpd_sends_the_file_to_the_queue(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice, tmp_path: Path
) -> None:
    source = tmp_path / "page.txt"
    source.write_bytes(b"hello printer\f")

    result = cli_runner.invoke(
        cli_root.cli, ["print", "lpd", "L2", str(source), "--job-name", "page", *_HOST], obj=services
    )

    assert result.exit_code == 0
    assert [(queue, job.name, job.data) for queue, job in device.lpd_jobs] == [("L2", "page", b"hello printer\f")]


def test_print_raw_reads_stdin_and_picks_the_printers_port(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    result = cli_runner.invoke(cli_root.cli, ["print", "raw", "3", "-", *_HOST], obj=services, input=b"\x1bE")

    assert result.exit_code == 0
    assert device.raw_sends == [(9102, b"\x1bE")]


def test_print_raw_with_empty_input_sends_nothing_and_exits_22(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    result = cli_runner.invoke(cli_root.cli, ["print", "raw", "1", "-", *_HOST], obj=services, input=b"")

    assert result.exit_code == 22
    assert device.raw_sends == []
