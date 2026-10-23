"""The ARP trick over an in-memory neighbour table and device."""

from __future__ import annotations

from ipaddress import IPv4Address
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sercomm_printserver.adapters.memory.device import FakeDevice, FakeTftp
from sercomm_printserver.adapters.memory.neighbors import FakeNeighborTable
from sercomm_printserver.application.arp_trick import assign_ip, borrowed_address, factory_reset, reach
from sercomm_printserver.application.print_server import DevicePorts, PrintServer
from sercomm_printserver.domain.config_codec import parse_config
from sercomm_printserver.domain.device_files import DeviceAction
from sercomm_printserver.domain.endpoint import DeviceEndpoint
from sercomm_printserver.domain.errors import ConfirmationRequiredError

if TYPE_CHECKING:
    from collections.abc import Callable

    from sercomm_printserver.application.ports import NeighborTable

_DUMPS = Path(__file__).resolve().parents[1] / "docs" / "device-dump"
_MAC = "00:c0:02:12:34:56"
_BORROWED = DeviceEndpoint(host="192.0.2.77")


def _device() -> FakeDevice:
    return FakeDevice(
        config=(_DUMPS / "CONFIG.txt").read_text(encoding="ascii"),
        psinf=(_DUMPS / "PSINF.txt").read_text(encoding="ascii"),
        monitor="",
    )


def _opener(device: FakeDevice) -> Callable[[DeviceEndpoint], PrintServer]:
    def open_server(endpoint: DeviceEndpoint) -> PrintServer:
        ports = DevicePorts(ftp=device, telnet=device, tftp=FakeTftp(device), lpd=device, raw=device, uptime=device)
        return PrintServer(endpoint, ports, sleep=lambda _seconds: None)

    return open_server


def test_the_fake_table_satisfies_the_port() -> None:
    table: NeighborTable = FakeNeighborTable()
    assert table.mac_of("192.0.2.1") is None


def test_reach_reads_the_device_and_leaves_no_entry_behind() -> None:
    table = FakeNeighborTable()

    result = reach(table, _opener(_device()), endpoint=_BORROWED, mac=_MAC)

    assert (result.device.default_name, result.borrowed_ip) == ("SC123456", "192.0.2.77")
    assert table.history == [("set", "192.0.2.77"), ("remove", "192.0.2.77")]
    assert table.entries == {}


def test_assign_ip_writes_a_static_address_and_restarts_the_device() -> None:
    device = _device()
    table = FakeNeighborTable()

    result = assign_ip(
        table, _opener(device), endpoint=_BORROWED, mac=_MAC, netmask=IPv4Address("255.255.0.0"), gateway=None
    )

    config = parse_config(device.config)
    assert (config.tcp_ip.ip_address, config.tcp_ip.netmask, config.tcp_ip.dhcp) == (
        IPv4Address("192.0.2.77"),
        IPv4Address("255.255.0.0"),
        False,
    )
    assert result.write is not None
    assert result.write.reachable_at == "192.0.2.77"
    assert device.actions == [DeviceAction.RESET]
    assert table.entries == {}


def test_factory_reset_needs_the_default_name_that_belongs_to_the_mac() -> None:
    device = _device()
    table = FakeNeighborTable()

    with pytest.raises(ConfirmationRequiredError, match="SC123456"):
        factory_reset(table, _opener(device), endpoint=_BORROWED, mac=_MAC, confirm_name="PS_EXAMPLE")
    assert (device.actions, table.history) == ([], [])

    factory_reset(table, _opener(device), endpoint=_BORROWED, mac=_MAC, confirm_name="sc123456")

    assert device.actions == [DeviceAction.FACTORY_DEFAULT]
    assert table.entries == {}


def test_a_device_whose_name_does_not_match_the_mac_is_refused_and_the_entry_removed() -> None:
    table = FakeNeighborTable()

    with pytest.raises(ConfirmationRequiredError, match="calls itself SC123456"):
        reach(table, _opener(_device()), endpoint=_BORROWED, mac="00:c0:02:aa:bb:cc")
    assert table.entries == {}


def test_an_address_another_host_holds_is_not_borrowed() -> None:
    table = FakeNeighborTable({"192.0.2.77": "aa:bb:cc:dd:ee:ff"})

    with (
        pytest.raises(ValueError, match="belongs to aa:bb:cc:dd:ee:ff"),
        borrowed_address(table, ip="192.0.2.77", mac=_MAC),
    ):
        pass
    assert table.entries == {"192.0.2.77": "aa:bb:cc:dd:ee:ff"}


def test_the_entry_is_removed_even_when_the_work_fails() -> None:
    table = FakeNeighborTable()

    with pytest.raises(RuntimeError), borrowed_address(table, ip="192.0.2.77", mac=_MAC):
        raise RuntimeError("device vanished")
    assert table.entries == {}
