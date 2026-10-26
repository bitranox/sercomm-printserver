"""End-to-end tests against the real test print server described in ``test-device.json``.

Run with ``SERCOMM_E2E=1 pytest -m device tests/test_e2e_device.py``. They run in file order,
from harmless to riskier: reading (through the library and the CLI), a RAW and an LPD job that
the restart in their finally clause clears, ``store-ip`` over a written but unapplied address, a
harmless parameter, the password, and
moving the device to a free address and back - once through CONFIG and, as root (``sudo``), once
through the ARP trick. Nothing here uploads firmware or restores factory defaults, and no test
opens a RAW print port without sending data (a bare connect occupies it for minutes).

A module fixture saves the device's CONFIG to ``.e2e/`` before anything runs and checks at the
end that the device holds exactly that configuration again - except the gateway, which ends at
``gateway`` from ``test-device.json`` by the user's decision (``gateway_found`` is what was there).
Waiting for a restart is the one place a test polls: a rebooting device signals nothing else.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from ipaddress import IPv4Address
from pathlib import Path
from typing import TYPE_CHECKING, cast

import ipscout
import pytest
from pydantic import BaseModel, ConfigDict, SecretStr

from sercomm_printserver.adapters.discovery import FtpBannerScanner
from sercomm_printserver.adapters.neighbors import IpscoutNeighborTable
from sercomm_printserver.adapters.snmp import SnmpUptime
from sercomm_printserver.adapters.tftp import TftpClient
from sercomm_printserver.application import arp_trick
from sercomm_printserver.composition import open_print_server
from sercomm_printserver.domain.config_codec import find_line, parse_config, render_config, with_value
from sercomm_printserver.domain.device_files import ReadableFile
from sercomm_printserver.domain.endpoint import DeviceEndpoint, PrintJob
from sercomm_printserver.domain.errors import DeviceResponseError, DeviceUnavailableError
from sercomm_printserver.domain.port_status import PortState, PortType

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sercomm_printserver.application.print_server import PrintServer

pytestmark = pytest.mark.device

_ROOT = Path(__file__).resolve().parents[1]
_SNAPSHOTS = _ROOT / ".e2e"
#: How long the monitor may take to show a RAW job's port as busy (measured: under 2 s).
_RAW_SETTLE_SECONDS = 10.0
#: The device refuses port 21 for about 0.1 s after each FTP session (docs/Manual-PS301.md);
#: 0.5 s after one, a probe was greeted every time (measured 3 of 3).
_FTP_SETTLE_SECONDS = 0.5
#: A RESET restarts the device about 5 s after its session ends (docs/Manual-PS301.md); a
#: trigger that does not restart it has shown no restart after this long.
_NO_RESTART_SECONDS = 8.0


class _E2eSettings(BaseModel):
    free_ip_candidates: list[IPv4Address]


class _TestDevice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: IPv4Address
    netmask: IPv4Address
    gateway: IPv4Address
    gateway_found: IPv4Address
    mac: str
    default_name: str
    box_name: str
    firmware: str
    ports: dict[str, str]
    e2e: _E2eSettings


@pytest.fixture(scope="module")
def device() -> _TestDevice:
    return _TestDevice.model_validate(json.loads((_ROOT / "test-device.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def server(device: _TestDevice) -> PrintServer:
    return open_print_server(DeviceEndpoint(host=str(device.host), timeout=10.0))


@pytest.fixture(scope="module", autouse=True)
def config_snapshot(device: _TestDevice) -> Iterator[str]:
    """Save CONFIG before the tests; afterwards require it back, with the target gateway."""
    start = open_print_server(DeviceEndpoint(host=str(device.host))).read_config_text()
    _SNAPSHOTS.mkdir(exist_ok=True)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (_SNAPSHOTS / f"{stamp}-CONFIG.txt").write_text(start, encoding="ascii")
    yield start
    final = parse_config(open_print_server(DeviceEndpoint(host=str(device.host))).read_config_text())
    # Only the gateway may differ: the IP test leaves the target value, a read-only run the found one.
    assert final.tcp_ip.gateway in {device.gateway, device.gateway_found}
    normalised = render_config(with_value(final, "GATEWAY", str(device.gateway_found)))
    assert normalised == render_config(with_value(parse_config(start), "GATEWAY", str(device.gateway_found))), (
        f"device configuration differs from the snapshot in {_SNAPSHOTS}"
    )


# ---------------------------------------------------------------- helpers


def _banner(host: str, *, timeout: float = 2.0) -> str | None:
    try:
        with socket.create_connection((host, 21), timeout=timeout) as connection:
            greeting = connection.recv(100).decode("ascii", "replace").strip()
            connection.sendall(b"QUIT\r\n")
            return greeting
    except OSError:
        return None


def _free_address(device: _TestDevice) -> str:
    """Return the first candidate nothing answers on - not ping, not FTP, not even ARP."""
    for candidate in device.e2e.free_ip_candidates:
        address = str(candidate)
        if ipscout.ping(address, 2).reached or _banner(address, timeout=1.0) is not None:
            continue
        # A host that drops ping and closes port 21 still answers ARP for the attempts above.
        if not _has_mac(address):
            return address
    pytest.fail("no free address among e2e.free_ip_candidates")


def _is_root() -> bool:
    if sys.platform == "win32":
        return False
    return os.geteuid() == 0


def _has_permanent_entry(address: str) -> bool:
    return any(
        entry.ip == address and entry.state is ipscout.NeighbourState.PERMANENT
        for entry in ipscout.neighbours(family=ipscout.AddressFamily.IPV4)
    )


def _has_mac(address: str) -> bool:
    return any(
        neighbour.ip == address and neighbour.mac for neighbour in ipscout.neighbours(family=ipscout.AddressFamily.IPV4)
    )


def _connect_ftp(host: str) -> socket.socket:
    """Connect to port 21, riding out the ~0.1 s the device refuses after each session."""
    deadline = time.monotonic() + 2.0
    while (connection := _try_connect(host)) is None:
        if time.monotonic() > deadline:
            pytest.fail(f"{host}:21 kept refusing connections for 2 s")
        time.sleep(0.05)
    return connection


def _try_connect(host: str) -> socket.socket | None:
    try:
        return socket.create_connection((host, 21), timeout=10)
    except ConnectionRefusedError:
        return None


def _uptime(host: str) -> float | None:
    """The SNMP uptime at ``host``, or None. The agent answers only at the device's own address."""
    try:
        return SnmpUptime().uptime(DeviceEndpoint(host=host, timeout=3.0))
    except (DeviceUnavailableError, DeviceResponseError):
        return None


def _cli(*arguments: str) -> tuple[int, dict[str, object]]:
    """Run the installed CLI as a user would, and return its exit code and JSON envelope."""
    done = subprocess.run(  # noqa: S603 - fixed interpreter and module, test-chosen arguments
        [sys.executable, "-m", "sercomm_printserver", *arguments, "--json-bare"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    envelope: dict[str, object] = json.loads(done.stdout)
    return done.returncode, envelope


def _login(host: str, user: str, password: str) -> str:
    """Return the device's reply to ``PASS`` (or to ``USER`` if that already decided)."""
    with _connect_ftp(host) as connection:
        replies = connection.makefile("rb")
        replies.readline()
        connection.sendall(f"USER {user}\r\n".encode("ascii"))
        reply = replies.readline().decode("ascii", "replace").strip()
        if reply.startswith("331"):
            connection.sendall(f"PASS {password}\r\n".encode("ascii"))
            reply = replies.readline().decode("ascii", "replace").strip()
        connection.sendall(b"QUIT\r\n")
        return reply


# ---------------------------------------------------------------- reading


def test_firmware_matches_the_recorded_version(server: PrintServer, device: _TestDevice) -> None:
    assert server.firmware_version() == device.firmware


def test_psinf_identifies_the_device(server: PrintServer, device: _TestDevice) -> None:
    info = server.info()

    assert (info.server_name, info.default_name, info.mac_address) == (device.box_name, device.default_name, device.mac)
    assert info.ip_address == device.host


def test_every_port_reports_its_status(server: PrintServer, device: _TestDevice) -> None:
    ports = server.status()

    assert {port.port: port.type for port in ports} == {
        name: PortType.SERIAL if kind == "serial" else PortType.PARALLEL for name, kind in device.ports.items()
    }


def _ports_on_direct_socket(server: PrintServer) -> set[str]:
    return {port.port for port in server.status() if port.occupied_by == "Direct Socket"}


def test_raw_data_for_l1_occupies_the_port_l1_is_routed_to(server: PrintServer) -> None:
    # The RAW ports belong to the logical printers L1..L3 and follow each one's routing. With no
    # printer attached the data stays queued and the port reads "Printing / Direct Socket" until
    # the restart in the finally clause clears it.
    routed_to = find_line(parse_config(server.read_config_text()), "L1_PROUT").value
    if any(port.state is not PortState.IDLE for port in server.status()):
        pytest.skip("a port is busy already; this test needs every port idle")
    busy: set[str] = set()
    try:
        server.print_raw(1, b"sercomm-printserver E2E RAW probe\r\n")
        deadline = time.monotonic() + _RAW_SETTLE_SECONDS
        while not busy and time.monotonic() < deadline:
            busy = _ports_on_direct_socket(server)
    finally:
        server.reset(wait=True)

    assert busy == {routed_to}
    assert all(port.state is PortState.IDLE for port in server.status())


def test_an_lpd_job_for_l1_occupies_the_port_l1_is_routed_to(server: PrintServer, device: _TestDevice) -> None:
    # With no printer ready the device takes the job but holds back its acknowledgement of the
    # data file (measured), so the submit times out; the port shows the job until the restart in
    # the finally clause clears it. Printing it for real needs a printer (OPEN-WORK [15]).
    routed_to = find_line(parse_config(server.read_config_text()), "L1_PROUT").value
    if any(port.state is not PortState.IDLE for port in server.status()):
        pytest.skip("a port is busy already; this test needs every port idle")
    impatient = open_print_server(DeviceEndpoint(host=str(device.host), timeout=3.0))
    busy: set[str] = set()
    queue = ""
    try:
        try:
            impatient.print_lpd("L1", PrintJob(data=b"sercomm-printserver E2E LPD probe\r\n", name="e2e-lpd"))
        except DeviceResponseError as error:
            if "data file" not in str(error):
                raise
        deadline = time.monotonic() + _RAW_SETTLE_SECONDS
        while not busy and time.monotonic() < deadline:
            busy = {port.port for port in server.status() if port.occupied_by == "LPD"}
        queue = server.queue_state("L1")
    finally:
        server.reset(wait=True)

    assert busy == {routed_to}
    assert "OCCUPIED BY: LPD" in queue
    assert all(port.state is PortState.IDLE for port in server.status())


def test_the_configuration_renders_back_byte_for_byte(server: PrintServer) -> None:
    text = server.read_config_text()

    assert render_config(parse_config(text)) == text


def test_the_lpd_queue_state_reports_the_port(server: PrintServer) -> None:
    assert "(P1)STATE:" in server.queue_state("L1")


def test_discovery_finds_the_device_with_its_mac(device: _TestDevice) -> None:
    scanner = FtpBannerScanner()
    # The scanner connects once per host, as a sweep must. An FTP session can end just before
    # this test (the module's CONFIG snapshot, when this test runs first), so wait out the
    # device's refusal window rather than read a refused connect as "no print server".
    time.sleep(_FTP_SETTLE_SECONDS)

    hits = scanner.probe_ftp([str(device.host)], timeout=3.0)

    assert [hit.greeting for hit in hits] == ["220 Print Server Ready."]
    assert scanner.mac_address(device.host) == device.mac


def test_tftp_reads_the_same_configuration_as_ftp(server: PrintServer, device: _TestDevice) -> None:
    via_tftp = TftpClient().retrieve(DeviceEndpoint(host=str(device.host), timeout=3.0), ReadableFile.CONFIG)

    assert via_tftp.decode("ascii") == server.read_config_text()


@pytest.mark.parametrize(
    ("arguments", "field", "expected"),
    [
        (("firmware",), "firmware", "firmware"),
        (("device-info",), "mac_address", "mac"),
        (("device-info",), "server_name", "box_name"),
        (("device-config", "get", "IP_ADDR"), "value", "host"),
        (("status",), "host", "host"),
        (("queue", "L1"), "queue", None),
        (("device-config", "show"), "host", "host"),
    ],
    ids=[
        "firmware",
        "device-info-mac",
        "device-info-name",
        "device-config-get",
        "status",
        "queue",
        "device-config-show",
    ],
)
def test_the_cli_reads_the_device(
    device: _TestDevice, arguments: tuple[str, ...], field: str, expected: str | None
) -> None:
    code, envelope = _cli(*arguments, "--host", str(device.host))

    assert (code, envelope["ok"]) == (0, True), envelope
    data = cast("dict[str, object]", envelope["data"])
    want = "L1" if expected is None else str(getattr(device, expected))
    assert str(data[field]) == want


def test_the_cli_discovers_the_device_with_its_mac(device: _TestDevice) -> None:
    time.sleep(_FTP_SETTLE_SECONDS)

    code, envelope = _cli("discover", "--network", f"{device.host}/32")

    assert (code, envelope["ok"]) == (0, True), envelope
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["devices"] == [{"host": str(device.host), "mac_address": device.mac}]


@pytest.mark.skipif(_is_root(), reason="as root the ARP request goes out, so nothing is refused")
def test_arp_reach_without_root_is_refused_before_anything_is_written(device: _TestDevice) -> None:
    # Unprivileged, this host can only read its ARP cache, which knows nothing about a free
    # address - so nothing shows the address is free, and the CLI refuses with exit 13.
    borrowed = _free_address(device)

    code, envelope = _cli("arp", "reach", "--mac", device.mac, "--ip", borrowed)

    assert code == 13, envelope
    assert envelope["error"] == "UnverifiedAddressError"
    assert not _has_permanent_entry(borrowed)


# ---------------------------------------------------------------- changing and restoring


@pytest.mark.skipif(not _is_root(), reason="writing a static ARP entry needs root; run this file with sudo")
def test_the_arp_trick_reaches_the_device_at_a_borrowed_address(device: _TestDevice) -> None:
    # Read-only on the device: PSINF over a borrowed address. The dashed, upper-case MAC is the
    # spelling a label shows; the static entry must be gone again afterwards.
    borrowed = _free_address(device)

    result = arp_trick.reach(
        IpscoutNeighborTable(),
        open_print_server,
        endpoint=DeviceEndpoint(host=borrowed, login=device.box_name),
        ip=IPv4Address(borrowed),
        mac=device.mac.upper().replace(":", "-"),
    )

    assert (result.device.default_name, str(result.borrowed_ip)) == (device.default_name, borrowed)
    assert str(result.device.ip_address) == str(device.host)
    assert not _has_permanent_entry(borrowed)


def test_store_ip_stores_the_running_address_over_a_written_one(server: PrintServer, device: _TestDevice) -> None:
    # SETIP stores the address the device runs on. The moment it differs from the stored one is
    # mid-move: a new IP_ADDR written but not applied. SETIP then writes the running address back
    # over it at once, without a restart (measured), so the device never leaves its address.
    home, away = str(device.host), _free_address(device)
    original = server.read_config()
    try:
        server.write_config(with_value(original, "IP_ADDR", away), apply=False)
        written = server.read_config().tcp_ip.ip_address
        before = _uptime(home)
        server.store_ip(confirm_name=device.box_name)
        stored = server.read_config().tcp_ip.ip_address
        time.sleep(_NO_RESTART_SECONDS)
        after = _uptime(home)
    finally:
        if server.read_config() != original:
            server.write_config(original, apply=False)

    assert (written, stored) == (IPv4Address(away), device.host)
    assert before is not None
    assert after is not None
    assert after > before + _NO_RESTART_SECONDS / 2, "store-ip must not restart the device"
    assert server.read_config() == original


def test_a_changed_contact_survives_the_restart_and_is_restored(server: PrintServer) -> None:
    original = server.read_config()
    marker = f"e2e {datetime.now(tz=timezone.utc):%H%M%S}"
    started = time.monotonic()

    result = server.write_config(with_value(original, "CONTACT", marker))
    print(f"write + restart took {time.monotonic() - started:.1f} s")

    snmp = server.read_config().snmp
    assert [change.token for change in result.changes] == ["CONTACT"]
    assert snmp is not None
    assert snmp.contact == marker
    server.write_config(original)
    assert server.read_config() == original


def test_a_password_can_be_set_and_cleared(server: PrintServer, device: _TestDevice) -> None:
    host = str(device.host)
    with_password = open_print_server(DeviceEndpoint(host=host, login=device.box_name, password=SecretStr("e2e-pw")))
    server.set_password(SecretStr("e2e-pw"))
    try:
        accepted_with_password = _login(host, device.box_name, "e2e-pw")
        with_empty = _login(host, device.box_name, "")
    finally:
        with_password.clear_password(confirm_name=device.box_name)

    assert accepted_with_password.startswith("230"), accepted_with_password
    assert not with_empty.startswith("230"), with_empty
    assert _login(host, device.box_name, "").startswith("230")


def test_the_device_moves_to_a_free_address_and_back(server: PrintServer, device: _TestDevice) -> None:
    home = str(device.host)
    away = _free_address(device)
    original = server.read_config()
    moved = with_value(with_value(original, "IP_ADDR", away), "GATEWAY", str(device.gateway))
    back = with_value(with_value(original, "IP_ADDR", home), "GATEWAY", str(device.gateway))

    result = server.write_config(moved)
    try:
        assert result.reachable_at == away
        assert _banner(home, timeout=2.0) is None, f"{home} still answers after the move to {away}"
        assert open_print_server(DeviceEndpoint(host=away)).read_config().tcp_ip.ip_address == IPv4Address(away)
    finally:
        returned = open_print_server(DeviceEndpoint(host=away)).write_config(back)

    assert returned.reachable_at == home
    assert server.read_config().tcp_ip.ip_address == device.host


@pytest.mark.skipif(not _is_root(), reason="writing a static ARP entry needs root; run this file with sudo")
def test_arp_assign_ip_moves_the_device_to_a_free_address_and_back(device: _TestDevice) -> None:
    # Away and back through the ARP trick alone, as for a device whose address is unknown.
    # The proof of each move is SNMP: the agent answers only at the device's own address, never
    # at a borrowed one (measured), so an answer once the static entry is gone means the device
    # really holds that address. A stale cache entry does not fool it.
    home, away = str(device.host), _free_address(device)
    table = IpscoutNeighborTable()
    original = open_print_server(DeviceEndpoint(host=home)).read_config()
    try:
        arp_trick.assign_ip(
            table,
            open_print_server,
            endpoint=DeviceEndpoint(host=away, login=device.box_name),
            ip=IPv4Address(away),
            mac=device.mac,
        )
        held_away = (_uptime(away) is not None, _uptime(home) is None)
        stored_away = open_print_server(DeviceEndpoint(host=away)).read_config().tcp_ip
        arp_trick.assign_ip(
            table,
            open_print_server,
            endpoint=DeviceEndpoint(host=home, login=device.box_name),
            ip=IPv4Address(home),
            mac=device.mac,
        )
    finally:
        if _uptime(home) is None and _uptime(away) is not None:
            open_print_server(DeviceEndpoint(host=away)).write_config(with_value(original, "IP_ADDR", home))

    assert held_away == (True, True), "after the move away the device answers SNMP at the new address only"
    assert (stored_away.ip_address, stored_away.dhcp) == (IPv4Address(away), False)
    assert (_uptime(home) is not None, _uptime(away) is None) == (True, True)
    assert open_print_server(DeviceEndpoint(host=home)).read_config().tcp_ip == original.tcp_ip
    assert not _has_permanent_entry(away)
    assert not _has_permanent_entry(home)
