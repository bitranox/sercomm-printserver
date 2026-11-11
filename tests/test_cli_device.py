"""Device commands end to end through the CLI, against the in-memory device.

The device stands behind every port, the CLI resolves it from ``--host`` (the in-memory
configuration has no ``[device]`` host), and each test reads what reached the device, not only
what was printed.
"""

from __future__ import annotations

import dataclasses
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from sercomm_printserver.adapters.cli import root as cli_root
from sercomm_printserver.adapters.cli.commands.device import CheckReport
from sercomm_printserver.adapters.memory.device import FakeDevice, FakeTftp
from sercomm_printserver.application.print_server import DevicePorts, PrintServer
from sercomm_printserver.composition import build_testing
from sercomm_printserver.domain.device_files import DeviceAction

if TYPE_CHECKING:
    from collections.abc import Callable

    from click.testing import CliRunner, Result

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


def test_the_firmware_envelope_is_written_byte_for_byte(
    cli_runner: CliRunner, services: Callable[[], AppServices]
) -> None:
    result = cli_runner.invoke(cli_root.cli, ["firmware", *_HOST, "--json-bare"], obj=services)

    assert result.stdout == (
        '{"ok":true,"command":"firmware","data":{"host":"192.0.2.52","firmware":"6022"},"skipped":[]}\n'
    )


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


def test_device_config_export_reports_the_path_as_given(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice, tmp_path: Path
) -> None:
    target = tmp_path / "CONFIG.txt"
    size = len(device.config.encode("ascii"))
    command = ["device-config", "export", str(target), *_HOST]

    human = cli_runner.invoke(cli_root.cli, command, obj=services)
    machine = cli_runner.invoke(cli_root.cli, [*command, "--json-bare"], obj=services)

    assert human.output == f"192.0.2.52: wrote {size} bytes to {target}\n"
    assert _json(machine.output)["data"] == {"host": "192.0.2.52", "path": str(target), "size": size}


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


def test_a_written_change_reports_the_flat_change_envelope(
    cli_runner: CliRunner, services: Callable[[], AppServices]
) -> None:
    result = cli_runner.invoke(
        cli_root.cli, ["device-config", "set", "CONTACT=lab", "--yes", *_HOST, "--json-bare"], obj=services
    )

    assert result.exit_code == 0
    assert result.stdout == (
        '{"ok":true,"command":"device-config set","data":{"host":"192.0.2.52",'
        '"changes":[{"number":6000,"token":"CONTACT","old":"","new":"lab"}],'
        '"written":true,"applied":true,"reachable_at":"192.0.2.52"},"skipped":[]}\n'
    )


def test_a_written_change_tells_a_person_what_changed(
    cli_runner: CliRunner, services: Callable[[], AppServices]
) -> None:
    result = cli_runner.invoke(cli_root.cli, ["device-config", "set", "CONTACT=lab", "--yes", *_HOST], obj=services)

    assert result.stdout == "CONTACT: '' -> 'lab'\n192.0.2.52: written, device restarted\n"


def test_a_change_to_the_same_value_writes_nothing_and_says_so(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    result = cli_runner.invoke(
        cli_root.cli, ["device-config", "set", "CONTACT=", "--yes", *_HOST, "--json-bare"], obj=services
    )

    data = _json(result.stdout)["data"]
    assert data == {
        "host": "192.0.2.52",
        "changes": [],
        "written": False,
        "applied": False,
        "reachable_at": "192.0.2.52",
    }
    assert device.actions == []


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


@pytest.mark.parametrize(
    ("args", "action"),
    [
        (["reset", "--yes", "--no-wait"], "reset"),
        (["factory-default", "--yes", "--confirm-name", "PS_EXAMPLE"], "factory-default"),
        (["store-ip", "--yes", "--confirm-name", "PS_EXAMPLE"], "store-ip"),
        (["password", "clear", "--yes", "--confirm-name", "PS_EXAMPLE"], "password clear"),
    ],
)
def test_an_action_names_itself_by_its_command_path(
    cli_runner: CliRunner, services: Callable[[], AppServices], args: list[str], action: str
) -> None:
    human = cli_runner.invoke(cli_root.cli, [*args, *_HOST], obj=services)
    machine = cli_runner.invoke(cli_root.cli, [*args, *_HOST, "--json-bare"], obj=services)

    assert human.stdout == f"192.0.2.52: {action} done\n"
    assert _json(machine.stdout)["data"] == {"host": "192.0.2.52", "action": action, "done": True}


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


class _PieceOnlyStdin(io.BytesIO):
    """Standard input that refuses a read of everything at once, as one too big for memory would."""

    def read(self, size: int | None = -1, /) -> bytes:
        if size is None or size < 0:
            raise AssertionError("the whole input was read at once instead of in pieces")
        return super().read(size)


#: Several 64 KiB pieces, so a streamed send is told apart from one read.
_STDIN_JOB = bytes(range(256)) * 1000


def _size(result: Result) -> object:
    data = _json(result.stdout)["data"]
    assert isinstance(data, dict)
    return cast("dict[str, object]", data)["size"]


def test_print_raw_streams_stdin_and_reports_the_bytes_sent(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    result = cli_runner.invoke(
        cli_root.cli, ["print", "raw", "1", "-", *_HOST, "--json-bare"], obj=services, input=_PieceOnlyStdin(_STDIN_JOB)
    )

    assert result.exit_code == 0, result.output
    assert device.raw_sends == [(9100, _STDIN_JOB)]
    assert _size(result) == len(_STDIN_JOB)


def test_print_raw_verify_streams_stdin_and_reports_the_bytes_sent(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    device.monitor_text = _IDLE_PORTS
    result = cli_runner.invoke(
        cli_root.cli,
        ["print", "raw", "3", "-", *_HOST, "--verify", "--json-bare"],
        obj=services,
        input=_PieceOnlyStdin(_STDIN_JOB),
    )

    assert result.exit_code == 0, result.output
    assert device.raw_sends == [(9102, _STDIN_JOB)]
    assert _size(result) == len(_STDIN_JOB)


def test_print_lpd_streams_stdin_and_reports_the_bytes_sent(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    arguments = ["print", "lpd", "L1", "-", *_HOST, "--json-bare"]
    result = cli_runner.invoke(cli_root.cli, arguments, obj=services, input=_PieceOnlyStdin(_STDIN_JOB))

    assert result.exit_code == 0, result.output
    assert [(queue, job.data) for queue, job in device.lpd_jobs] == [("L1", _STDIN_JOB)]
    assert _size(result) == len(_STDIN_JOB)


@pytest.mark.parametrize("transport", [["raw", "1"], ["lpd", "L1"]])
def test_print_reports_the_size_of_a_file_argument(
    cli_runner: CliRunner, services: Callable[[], AppServices], tmp_path: Path, transport: list[str]
) -> None:
    source = tmp_path / "page.prn"
    source.write_bytes(_STDIN_JOB)

    result = cli_runner.invoke(cli_root.cli, ["print", *transport, str(source), *_HOST, "--json-bare"], obj=services)

    assert result.exit_code == 0, result.output
    assert _size(result) == len(_STDIN_JOB)


def test_print_raw_refuses_empty_stdin_before_contacting_the_device(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    result = cli_runner.invoke(cli_root.cli, ["print", "raw", "1", "-", *_HOST], obj=services, input=b"")

    assert result.exit_code == 22
    assert device.retrieved == []
    assert device.raw_sends == []


def test_print_lpd_reports_the_transport_and_queue_as_fields(
    cli_runner: CliRunner, services: Callable[[], AppServices]
) -> None:
    human = cli_runner.invoke(cli_root.cli, ["print", "lpd", "L2", "-", *_HOST], obj=services, input=b"x")
    machine = cli_runner.invoke(
        cli_root.cli, ["print", "lpd", "L2", "-", *_HOST, "--json-bare"], obj=services, input=b"x"
    )

    assert human.stdout == "192.0.2.52: sent 1 bytes to LPD queue L2\n"
    assert machine.stdout == (
        '{"ok":true,"command":"print lpd","data":{"host":"192.0.2.52","transport":"lpd",'
        '"queue":"L2","printer":null,"size":1},"skipped":[]}\n'
    )


def test_print_raw_reports_the_transport_and_printer_as_fields(
    cli_runner: CliRunner, services: Callable[[], AppServices]
) -> None:
    human = cli_runner.invoke(cli_root.cli, ["print", "raw", "1", "-", *_HOST], obj=services, input=b"x")
    machine = cli_runner.invoke(
        cli_root.cli, ["print", "raw", "1", "-", *_HOST, "--json-bare"], obj=services, input=b"x"
    )

    assert human.stdout == "192.0.2.52: sent 1 bytes to RAW port of L1\n"
    assert machine.stdout == (
        '{"ok":true,"command":"print raw","data":{"host":"192.0.2.52","transport":"raw",'
        '"queue":null,"printer":1,"size":1},"skipped":[]}\n'
    )


def test_print_raw_to_a_logical_printer_without_a_raw_port_is_a_usage_error(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    result = cli_runner.invoke(cli_root.cli, ["print", "raw", "4", "-", *_HOST], obj=services, input=b"\x1bE")

    assert result.exit_code == 2
    assert device.raw_sends == []


def test_print_raw_with_empty_input_sends_nothing_and_exits_22(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    result = cli_runner.invoke(cli_root.cli, ["print", "raw", "1", "-", *_HOST], obj=services, input=b"")

    assert result.exit_code == 22
    assert device.raw_sends == []


_IDLE_PORTS = (
    "(P1)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n\r\n"
    "(P2)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n\r\n"
    "(SP)STATE: Idle\r\nTYPE: Serial\r\nPRINTER STATUS: On-Line\r\n"
)


def test_print_raw_verify_reports_the_port_that_went_idle(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    device.monitor_text = _IDLE_PORTS

    human = cli_runner.invoke(cli_root.cli, ["print", "raw", "3", "-", *_HOST, "--verify"], obj=services, input=b"x")
    machine = cli_runner.invoke(
        cli_root.cli, ["print", "raw", "3", "-", *_HOST, "--verify", "--json-bare"], obj=services, input=b"x"
    )

    assert human.exit_code == 0
    assert human.stdout == "192.0.2.52: sent 1 bytes to RAW port of L3; SP is Idle again\n"
    assert machine.stdout == (
        '{"ok":true,"command":"print raw","data":{"host":"192.0.2.52","transport":"raw",'
        '"queue":null,"printer":3,"size":1,"idle_port":"SP"},"skipped":[]}\n'
    )


def test_print_raw_verify_exits_75_and_sends_nothing_when_the_port_stays_busy_before_the_send(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    # The dumped monitor text has every port "Printing / Direct Socket".
    result = cli_runner.invoke(
        cli_root.cli,
        ["print", "raw", "3", "-", *_HOST, "--verify", "--verify-timeout", "0.1", "--json-bare"],
        obj=services,
        input=b"x",
    )

    assert result.exit_code == 75
    envelope = _json(result.stdout)
    assert (envelope["ok"], envelope["error"]) == (False, "PortBusyError")
    # The fake accepts the probe of 9102, so the refusal names the wedge.
    assert "nothing was sent, SP is wedged" in str(envelope["message"])
    assert device.raw_sends == []


def test_print_raw_verify_exits_110_when_the_port_stays_busy_after_the_send(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    # Free for the read before the send, then the dumped text: every port "Printing / Direct Socket".
    device.monitor_replies = [_IDLE_PORTS]

    result = cli_runner.invoke(
        cli_root.cli,
        ["print", "raw", "3", "-", *_HOST, "--verify", "--verify-timeout", "0.1", "--json-bare"],
        obj=services,
        input=b"x",
    )

    assert result.exit_code == 110
    envelope = _json(result.stdout)
    assert (envelope["ok"], envelope["error"]) == (False, "JobNotDrainedError")
    assert "the data was sent, but SP is wedged" in str(envelope["message"])
    assert device.raw_sends == [(9102, b"x")]


def test_print_raw_verify_timeout_without_verify_is_a_usage_error(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    # Taking the value and not watching would read as a verified print that was never verified.
    result = cli_runner.invoke(
        cli_root.cli, ["print", "raw", "1", "-", *_HOST, "--verify-timeout", "5"], obj=services, input=b"x"
    )

    assert result.exit_code == 2
    assert "--verify-timeout needs --verify" in result.stderr
    assert device.raw_sends == []


# ---------------------------------------------------------------- check


def test_check_reports_every_port_and_exits_3_on_a_wedge(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    # The dumped monitor shows all three ports Printing / Direct Socket / 0 bytes; the fake
    # accepts every probe, so each one is wedged.
    result = cli_runner.invoke(cli_root.cli, ["check", *_HOST], obj=services)

    assert result.exit_code == 3
    rows = [line.split() for line in result.output.splitlines()[1:4]]
    assert [(row[0], row[2]) for row in rows] == [("P1", "wedged"), ("P2", "wedged"), ("SP", "wedged")]
    assert "check --reset --yes" in result.output
    assert device.raw_probes == [9100, 9101, 9102]
    assert device.raw_sends == []
    assert device.actions == []


def test_check_answers_as_an_envelope_that_is_not_ok_on_a_wedge(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    device.raw_refusing = {9100, 9101}

    result = cli_runner.invoke(cli_root.cli, ["check", *_HOST, "--json-bare"], obj=services)

    envelope = _json(result.output)
    assert result.exit_code == 3
    assert (envelope["ok"], envelope["command"]) == (False, "check")
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["wedged"] is True
    report = CheckReport.model_validate(data)
    assert report.restarted is False
    assert [(port.status.port.value, port.verdict.value, port.probed) for port in report.ports] == [
        ("P1", "held", (9100,)),
        ("P2", "held", (9101,)),
        ("SP", "wedged", (9102,)),
    ]


def test_check_of_a_healthy_device_exits_0(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    device.monitor_text = _IDLE_PORTS

    result = cli_runner.invoke(cli_root.cli, ["check", *_HOST, "--json-bare"], obj=services)

    assert result.exit_code == 0
    assert _json(result.output)["ok"] is True
    assert device.raw_probes == []


def test_check_reset_without_yes_exits_77_and_probes_nothing(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    result = cli_runner.invoke(cli_root.cli, ["check", "--reset", *_HOST], obj=services)

    assert result.exit_code == 77
    assert device.actions == []
    assert device.raw_probes == []


def test_check_reset_restarts_a_wedged_device_and_exits_0_once_it_is_clear(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    device.restart_after_reads = 1
    device.monitor_replies = [device.monitor_text, _IDLE_PORTS]

    result = cli_runner.invoke(cli_root.cli, ["check", "--reset", "--yes", *_HOST], obj=services)

    assert result.exit_code == 0, result.output
    assert device.actions == [DeviceAction.RESET]
    assert "restarted" in result.output.lower()
    assert "P1, P2, SP" in result.output


def test_check_reset_exits_3_when_the_wedge_survives_the_restart(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    device.restart_after_reads = 1

    result = cli_runner.invoke(cli_root.cli, ["check", "--reset", "--yes", *_HOST, "--json-bare"], obj=services)

    envelope = _json(result.output)
    data = envelope["data"]
    assert isinstance(data, dict)
    assert result.exit_code == 3
    assert (envelope["ok"], data["restarted"], data["wedged"]) == (False, True, True)
    assert device.actions == [DeviceAction.RESET]


def test_check_reset_leaves_a_device_with_nothing_wedged_alone(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice
) -> None:
    device.raw_refusing = {9100, 9101, 9102}

    result = cli_runner.invoke(cli_root.cli, ["check", "--reset", "--yes", *_HOST], obj=services)

    assert result.exit_code == 0
    assert device.actions == []
