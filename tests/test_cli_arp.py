"""The ``arp`` commands end to end through the CLI, against an in-memory device and neighbour table.

Each test reads what reached the device and what the neighbour table saw, not only what was
printed: the table's history is the proof that the borrowed entry was set and removed again.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sercomm_printserver.adapters.cli import root as cli_root
from sercomm_printserver.adapters.memory.device import FakeDevice, FakeTftp
from sercomm_printserver.adapters.memory.neighbors import FakeNeighborTable
from sercomm_printserver.application.print_server import DevicePorts, PrintServer
from sercomm_printserver.composition import build_testing
from sercomm_printserver.domain.config_codec import parse_config
from sercomm_printserver.domain.device_files import DeviceAction
from sercomm_printserver.domain.errors import HostPrivilegeError

if TYPE_CHECKING:
    from collections.abc import Callable

    from click.testing import CliRunner

    from sercomm_printserver.application.ports import NeighborTable
    from sercomm_printserver.composition import AppServices
    from sercomm_printserver.domain.endpoint import DeviceEndpoint

_DUMPS = Path(__file__).resolve().parents[1] / "docs" / "device-dump"
_MAC = "00:c0:02:12:34:56"
_TARGET = ["--mac", _MAC, "--ip", "192.0.2.77"]


@pytest.fixture
def device() -> FakeDevice:
    return FakeDevice(
        config=(_DUMPS / "CONFIG.txt").read_text(encoding="ascii"),
        psinf=(_DUMPS / "PSINF.txt").read_text(encoding="ascii"),
        monitor="",
    )


@pytest.fixture
def table() -> FakeNeighborTable:
    return FakeNeighborTable()


def _services(device: FakeDevice, table: NeighborTable) -> Callable[[], AppServices]:
    def open_print_server(endpoint: DeviceEndpoint, *, raw_port_base: int) -> PrintServer:
        ports = DevicePorts(ftp=device, telnet=device, tftp=FakeTftp(device), lpd=device, raw=device, uptime=device)
        return PrintServer(endpoint, ports, raw_port_base=raw_port_base, sleep=lambda _seconds: None)

    def open_neighbor_table(*, interface: str | None = None) -> NeighborTable:
        del interface
        return table

    return lambda: dataclasses.replace(
        build_testing(), open_print_server=open_print_server, open_neighbor_table=open_neighbor_table
    )


def _json(output: str) -> dict[str, object]:
    document: dict[str, object] = json.loads(output)
    return document


def test_arp_reach_reports_the_device_and_removes_the_entry(
    cli_runner: CliRunner, device: FakeDevice, table: FakeNeighborTable
) -> None:
    result = cli_runner.invoke(cli_root.cli, ["arp", "reach", *_TARGET, "--json-bare"], obj=_services(device, table))

    assert result.exit_code == 0, result.output
    envelope = _json(result.stdout)
    assert (envelope["ok"], envelope["command"]) == (True, "arp reach")
    data = envelope["data"]
    assert isinstance(data, dict)
    assert (data["mac_address"], data["borrowed_ip"], data["write"]) == (_MAC, "192.0.2.77", None)
    assert table.history == [("set", "192.0.2.77"), ("remove", "192.0.2.77")]
    assert device.actions == []


def test_arp_assign_ip_without_yes_changes_nothing(
    cli_runner: CliRunner, device: FakeDevice, table: FakeNeighborTable
) -> None:
    before = device.config

    result = cli_runner.invoke(cli_root.cli, ["arp", "assign-ip", *_TARGET], obj=_services(device, table))

    assert result.exit_code == 77
    assert "--yes" in result.output
    assert (device.config, device.actions, table.history) == (before, [], [])


def test_arp_assign_ip_stores_the_borrowed_address_and_restarts_the_device(
    cli_runner: CliRunner, device: FakeDevice, table: FakeNeighborTable
) -> None:
    result = cli_runner.invoke(
        cli_root.cli,
        ["arp", "assign-ip", *_TARGET, "--netmask", "255.255.0.0", "--gateway", "192.0.2.1", "--yes"],
        obj=_services(device, table),
    )

    assert result.exit_code == 0, result.output
    tcp_ip = parse_config(device.config).tcp_ip
    assert (str(tcp_ip.ip_address), str(tcp_ip.netmask), str(tcp_ip.gateway), tcp_ip.dhcp) == (
        "192.0.2.77",
        "255.255.0.0",
        "192.0.2.1",
        False,
    )
    assert device.actions == [DeviceAction.RESET]
    assert "answers at:  192.0.2.77" in result.output
    assert table.entries == {}


def test_arp_assign_ip_refuses_a_malformed_netmask_before_touching_anything(
    cli_runner: CliRunner, device: FakeDevice, table: FakeNeighborTable
) -> None:
    result = cli_runner.invoke(
        cli_root.cli, ["arp", "assign-ip", *_TARGET, "--netmask", "255.255.0", "--yes"], obj=_services(device, table)
    )

    assert result.exit_code == 22
    assert "--netmask" in result.output
    assert (device.actions, table.history) == ([], [])


def test_arp_factory_reset_needs_the_default_name_of_the_mac(
    cli_runner: CliRunner, device: FakeDevice, table: FakeNeighborTable
) -> None:
    refused = cli_runner.invoke(
        cli_root.cli,
        ["arp", "factory-reset", *_TARGET, "--yes", "--confirm-name", "PS_EXAMPLE"],
        obj=_services(device, table),
    )
    done = cli_runner.invoke(
        cli_root.cli,
        ["arp", "factory-reset", *_TARGET, "--yes", "--confirm-name", "SC123456"],
        obj=_services(device, table),
    )

    assert refused.exit_code == 77
    assert "SC123456" in refused.output
    assert done.exit_code == 0, done.output
    assert device.actions == [DeviceAction.FACTORY_DEFAULT]
    assert table.entries == {}


class _RefusingTable(FakeNeighborTable):
    """A host that may not write its neighbour table, as an unprivileged process sees it."""

    def set_static(self, ip: str, mac: str) -> None:
        raise HostPrivilegeError("changing the neighbour table needs root or CAP_NET_ADMIN")


def test_arp_without_admin_rights_exits_13_and_never_talks_to_the_device(
    cli_runner: CliRunner, device: FakeDevice
) -> None:
    table = _RefusingTable()

    result = cli_runner.invoke(cli_root.cli, ["arp", "reach", *_TARGET], obj=_services(device, table))

    assert result.exit_code == 13
    assert "CAP_NET_ADMIN" in result.output
    assert (table.history, device.actions) == ([], [])
