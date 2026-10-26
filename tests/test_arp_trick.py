"""The ARP trick over an in-memory neighbour table and device."""

from __future__ import annotations

from ipaddress import IPv4Address
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sercomm_printserver.adapters.memory.device import FakeDevice, FakeTftp
from sercomm_printserver.adapters.memory.neighbors import FakeNeighborTable, NeighborOperation
from sercomm_printserver.application.arp_trick import ArpResult, assign_ip, borrowed_address, factory_reset, reach
from sercomm_printserver.application.print_server import DevicePorts, PrintServer
from sercomm_printserver.domain.config_codec import parse_config, render_config, with_value
from sercomm_printserver.domain.device_files import DeviceAction
from sercomm_printserver.domain.device_info import normalise_mac, parse_psinf
from sercomm_printserver.domain.endpoint import DeviceEndpoint
from sercomm_printserver.domain.errors import ConfigFormatError, ConfirmationRequiredError, UnverifiedAddressError
from sercomm_printserver.domain.neighbor import AddressHolder, LookupMethod

if TYPE_CHECKING:
    from collections.abc import Callable

    from sercomm_printserver.application.ports import NeighborTable

_DUMPS = Path(__file__).resolve().parents[1] / "docs" / "device-dump"
_MAC = "00:c0:02:12:34:56"
_DEVICE_MAC = normalise_mac(_MAC)
_IP = IPv4Address("192.0.2.77")
#: The session settings; arp_trick puts the borrowed address in place of the host.
_SESSION = DeviceEndpoint(host="unused.example")
_SET_AND_REMOVED = [(NeighborOperation.SET, _IP), (NeighborOperation.REMOVE, _IP)]


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
    assert table.holder_of(IPv4Address("192.0.2.1")) == AddressHolder(mac=None, method=LookupMethod.ACTIVE)


def test_reach_reads_the_device_and_leaves_no_entry_behind() -> None:
    table = FakeNeighborTable()

    result = reach(table, _opener(_device()), endpoint=_SESSION, ip=_IP, mac=_MAC)

    assert (result.device.default_name, result.borrowed_ip) == ("SC123456", _IP)
    assert table.history == _SET_AND_REMOVED
    assert table.entries == {}


def test_the_session_settings_reach_the_device_at_the_borrowed_address() -> None:
    device = _device()
    opened: list[DeviceEndpoint] = []

    def open_server(endpoint: DeviceEndpoint) -> PrintServer:
        opened.append(endpoint)
        return _opener(device)(endpoint)

    session = DeviceEndpoint(host="unused.example", login="SC123456", timeout=3.0)
    reach(FakeNeighborTable(), open_server, endpoint=session, ip=_IP, mac=_MAC)

    assert opened == [session.model_copy(update={"host": "192.0.2.77"})]


def test_the_result_serialises_the_typed_mac_and_address_as_plain_text() -> None:
    device = parse_psinf((_DUMPS / "PSINF.txt").read_text(encoding="ascii"))

    result = ArpResult(mac_address=_DEVICE_MAC, borrowed_ip=_IP, device=device)

    assert result.model_dump_json().startswith('{"mac_address":"00:c0:02:12:34:56","borrowed_ip":"192.0.2.77",')


def test_assign_ip_writes_a_static_address_and_restarts_the_device() -> None:
    device = _device()
    table = FakeNeighborTable()

    result = assign_ip(
        table, _opener(device), endpoint=_SESSION, ip=_IP, mac=_MAC, netmask=IPv4Address("255.255.0.0"), gateway=None
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
        factory_reset(table, _opener(device), endpoint=_SESSION, ip=_IP, mac=_MAC, confirm_name="PS_EXAMPLE")
    assert (device.actions, table.history) == ([], [])

    factory_reset(table, _opener(device), endpoint=_SESSION, ip=_IP, mac=_MAC, confirm_name="sc123456")

    assert device.actions == [DeviceAction.FACTORY_DEFAULT]
    assert table.entries == {}


def test_a_device_whose_name_does_not_match_the_mac_is_refused_and_the_entry_removed() -> None:
    table = FakeNeighborTable()

    with pytest.raises(ConfirmationRequiredError, match="calls itself SC123456"):
        reach(table, _opener(_device()), endpoint=_SESSION, ip=_IP, mac="00:c0:02:aa:bb:cc")
    assert table.entries == {}


def test_an_address_another_host_holds_is_not_borrowed() -> None:
    holder = normalise_mac("aa:bb:cc:dd:ee:ff")
    table = FakeNeighborTable({_IP: holder})

    with (
        pytest.raises(ValueError, match="belongs to aa:bb:cc:dd:ee:ff"),
        borrowed_address(table, ip=_IP, mac=_DEVICE_MAC),
    ):
        pass
    assert table.entries == {_IP: holder}


def test_an_address_only_the_cache_knows_nothing_about_is_not_borrowed() -> None:
    # The cache knows only hosts this machine has talked to, so its silence proves nothing.
    table = FakeNeighborTable(method=LookupMethod.CACHE)

    with (
        pytest.raises(UnverifiedAddressError, match=r"cannot tell whether 192\.0\.2\.77 is free"),
        borrowed_address(table, ip=_IP, mac=_DEVICE_MAC),
    ):
        pass
    assert table.history == []


def test_the_cache_still_shows_an_address_another_host_holds() -> None:
    holder = normalise_mac("aa:bb:cc:dd:ee:ff")
    table = FakeNeighborTable({_IP: holder}, method=LookupMethod.CACHE)

    with (
        pytest.raises(ValueError, match="belongs to aa:bb:cc:dd:ee:ff"),
        borrowed_address(table, ip=_IP, mac=_DEVICE_MAC),
    ):
        pass
    assert table.history == []


def test_an_address_the_cache_maps_to_the_device_is_borrowed_again() -> None:
    table = FakeNeighborTable({_IP: _DEVICE_MAC}, method=LookupMethod.CACHE)

    reach(table, _opener(_device()), endpoint=_SESSION, ip=_IP, mac=_MAC)

    assert table.history == _SET_AND_REMOVED


def test_an_address_this_host_already_maps_to_the_device_is_borrowed_again() -> None:
    table = FakeNeighborTable({_IP: _DEVICE_MAC})

    result = reach(table, _opener(_device()), endpoint=_SESSION, ip=_IP, mac="00-C0-02-12-34-56")

    assert result.mac_address == _MAC
    assert table.history == _SET_AND_REMOVED


def test_the_entry_is_removed_even_when_the_work_fails() -> None:
    table = FakeNeighborTable()

    with pytest.raises(RuntimeError), borrowed_address(table, ip=_IP, mac=_DEVICE_MAC):
        raise RuntimeError("device vanished")
    assert table.entries == {}


@pytest.mark.parametrize("spelling", ["00-C0-02-12-34-56", "00c002123456", "00c0.0212.3456", " 00:C0:02:12:34:56 "])
def test_every_common_mac_spelling_reaches_the_same_device(spelling: str) -> None:
    table = FakeNeighborTable()

    result = reach(table, _opener(_device()), endpoint=_SESSION, ip=_IP, mac=spelling)

    assert result.mac_address == _MAC
    assert table.history == _SET_AND_REMOVED


@pytest.mark.parametrize(
    "bad", ["00:c0:02:12:34", "00:c0:02:12:34:5g", "00:c0-02:12:34:56", "00:c0:02:12:34:5" + chr(0x0666)]
)
def test_a_malformed_mac_is_refused_before_any_entry_is_written(bad: str) -> None:
    table = FakeNeighborTable()

    with pytest.raises(ValueError, match="is not a MAC address"):
        reach(table, _opener(_device()), endpoint=_SESSION, ip=_IP, mac=bad)
    assert table.history == []


def _token_level_config(device: FakeDevice, *, netmask: str | None, gateway: str | None) -> str:
    """What the device must receive: its CONFIG with the four parameters set token by token."""
    expected = with_value(with_value(parse_config(device.config), "IP_ADDR", "192.0.2.77"), "DHCP_MODE", "Disable")
    if netmask is not None:
        expected = with_value(expected, "MASK", netmask)
    if gateway is not None:
        expected = with_value(expected, "GATEWAY", gateway)
    return render_config(expected)


@pytest.mark.parametrize(
    ("netmask", "gateway"),
    [(None, None), ("255.255.0.0", None), (None, "192.0.2.254"), ("255.255.255.128", "192.0.2.126")],
)
def test_assign_ip_uploads_exactly_the_config_a_token_level_edit_produces(
    netmask: str | None, gateway: str | None
) -> None:
    # Start from DHCP on, so switching it off is part of what the upload must carry.
    device = _device()
    device.config = device.config.replace("DHCP_MODE:Disable", "DHCP_MODE:Enable")
    assert parse_config(device.config).tcp_ip.dhcp is True
    expected = _token_level_config(device, netmask=netmask, gateway=gateway)

    assign_ip(
        FakeNeighborTable(),
        _opener(device),
        endpoint=_SESSION,
        ip=_IP,
        mac=_MAC,
        netmask=None if netmask is None else IPv4Address(netmask),
        gateway=None if gateway is None else IPv4Address(gateway),
    )

    assert device.config == expected


def test_assign_ip_refuses_firmware_without_a_dhcp_switch_and_writes_nothing() -> None:
    # Firmware 6A10 has no DHCP_MODE line, so assign-ip cannot switch DHCP off there.
    device = FakeDevice(
        config=(_DUMPS / "fw6a10" / "CONFIG.txt").read_text(encoding="ascii"),
        psinf=(_DUMPS / "PSINF.txt").read_text(encoding="ascii"),
        monitor="",
    )
    before = device.config
    table = FakeNeighborTable()

    with pytest.raises(ConfigFormatError, match="DHCP_MODE"):
        assign_ip(table, _opener(device), endpoint=_SESSION, ip=_IP, mac=_MAC)

    assert (device.config, device.actions, table.entries) == (before, [], {})
