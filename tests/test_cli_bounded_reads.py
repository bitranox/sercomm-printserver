"""Files a CLI command reads from the operator are read only as far as the command needs.

A CONFIG import reads a file the device itself produced (about 2 KB), so a much larger file is
not a CONFIG and is refused without being read whole. A password file supplies its first line,
so only that line is read.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sercomm_printserver.adapters.cli import root as cli_root
from sercomm_printserver.adapters.cli.commands.device_config import CONFIG_FILE_LIMIT
from sercomm_printserver.adapters.memory.device import FakeDevice, FakeTftp
from sercomm_printserver.application.print_server import DevicePorts, PrintServer
from sercomm_printserver.composition import build_testing

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


def _error(output: str) -> str:
    document: dict[str, object] = json.loads(output)
    return str(document["error"])


def test_a_config_file_above_the_limit_is_refused_and_nothing_is_written(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice, tmp_path: Path
) -> None:
    before = device.config
    exported = (_DUMPS / "CONFIG.txt").read_text(encoding="ascii")
    oversized = tmp_path / "CONFIG.txt"
    # Just past the limit, so a limit moved up by a little no longer refuses it.
    oversized.write_text(exported + "#" * (CONFIG_FILE_LIMIT + 1 - len(exported)), encoding="ascii")

    result = cli_runner.invoke(
        cli_root.cli, ["device-config", "import", str(oversized), "--yes", *_HOST, "--json-bare"], obj=services
    )

    assert result.exit_code == 22
    assert _error(result.output) == "ConfigFormatError"
    assert f"larger than {CONFIG_FILE_LIMIT} bytes" in result.output
    assert device.config == before


def test_a_config_file_at_the_limit_is_still_read(
    cli_runner: CliRunner, services: Callable[[], AppServices], device: FakeDevice, tmp_path: Path
) -> None:
    exported = (_DUMPS / "CONFIG.txt").read_text(encoding="ascii")
    at_limit = tmp_path / "CONFIG.txt"
    at_limit.write_text(exported, encoding="ascii")
    assert at_limit.stat().st_size <= CONFIG_FILE_LIMIT

    result = cli_runner.invoke(
        cli_root.cli, ["device-config", "import", str(at_limit), "--yes", *_HOST, "--json-bare"], obj=services
    )

    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("first\r\nsecond\r\n", "first"),
        ("only-line", "only-line"),
        ("first\n" + "x" * 200_000, "first"),
        ("", ""),
    ],
)
def test_the_password_comes_from_the_first_line_of_the_file(
    *,
    cli_runner: CliRunner,
    services: Callable[[], AppServices],
    device: FakeDevice,
    tmp_path: Path,
    content: str,
    expected: str,
) -> None:
    secret_file = tmp_path / "pw.txt"
    secret_file.write_bytes(content.encode("utf-8"))

    result = cli_runner.invoke(
        cli_root.cli, ["password", "set", "--from-file", str(secret_file), "--yes", *_HOST, "--json-bare"], obj=services
    )

    assert result.exit_code == 0, result.output
    assert device.credential == expected
