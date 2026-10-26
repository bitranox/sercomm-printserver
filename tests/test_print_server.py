"""PrintServer use cases against the in-memory device, which stands behind every port."""

from __future__ import annotations

from ipaddress import IPv4Address
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from sercomm_printserver.adapters.memory.device import FakeDevice, FakeTftp
from sercomm_printserver.application.print_server import DevicePorts, PrintServer
from sercomm_printserver.domain.config_codec import render_config, with_value
from sercomm_printserver.domain.device_files import DeviceAction
from sercomm_printserver.domain.endpoint import DeviceEndpoint, PrintJob
from sercomm_printserver.domain.errors import (
    AuthenticationRequiredError,
    ConfirmationRequiredError,
    DeviceResponseError,
    DeviceUnavailableError,
)
from sercomm_printserver.domain.port_status import PortState

if TYPE_CHECKING:
    from collections.abc import Callable

    from sercomm_printserver.application.ports import FtpPort, LpdPort, RawPort, TelnetPort, TftpPort

_DUMPS = Path(__file__).resolve().parents[1] / "docs" / "device-dump"
_ENDPOINT = DeviceEndpoint(host="192.0.2.52")


def _device(*, login_for_writes: str | None = None) -> FakeDevice:
    return FakeDevice(
        config=(_DUMPS / "CONFIG.txt").read_text(encoding="ascii"),
        psinf=(_DUMPS / "PSINF.txt").read_text(encoding="ascii"),
        monitor="(P1)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n",
        login_for_writes=login_for_writes,
    )


class _ManualClock:
    """A clock that moves only when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _server(
    device: FakeDevice, *, endpoint: DeviceEndpoint = _ENDPOINT, clock: _ManualClock | None = None
) -> PrintServer:
    ports = DevicePorts(ftp=device, telnet=device, tftp=FakeTftp(device), lpd=device, raw=device, uptime=device)
    clock = clock or _ManualClock()
    return PrintServer(endpoint, ports, sleep=clock.sleep, clock=clock)


def test_the_fake_device_satisfies_every_port() -> None:
    device = _device()
    ftp: FtpPort = device
    telnet: TelnetPort = device
    tftp: TftpPort = FakeTftp(device)
    lpd: LpdPort = device
    raw: RawPort = device
    assert (ftp, telnet, tftp, lpd, raw) is not None


# ---------------------------------------------------------------- reading


def test_reading_returns_typed_reports() -> None:
    server = _server(_device())

    assert server.firmware_version() == "6022"
    assert server.info().server_name == "PS_EXAMPLE"
    assert server.status()[0].state is PortState.IDLE
    assert server.read_config().tcp_ip.ip_address == IPv4Address("192.0.2.52")


def test_a_garbled_syst_version_falls_back_to_the_psinf_report() -> None:
    device = _device()
    device.firmware = "\u00c4^\u00f0&"

    assert _server(device).firmware_version() == "6022"


def test_the_config_text_comes_back_exactly_as_the_device_sent_it() -> None:
    device = _device()

    assert _server(device).read_config_text() == device.config


def test_an_unreachable_device_surfaces_as_device_unavailable() -> None:
    device = _device()
    device.reachable = False

    with pytest.raises(DeviceUnavailableError):
        _server(device).firmware_version()


# ---------------------------------------------------------------- writing the configuration


def test_writing_an_unchanged_configuration_uploads_nothing() -> None:
    device = _device()
    server = _server(device)

    result = server.write_config(server.read_config())

    assert (result.written, result.applied, result.changes) == (False, False, ())
    assert device.actions == []


def test_a_changed_configuration_is_uploaded_verified_and_applied_by_a_reset() -> None:
    device = _device()
    server = _server(device)
    new = with_value(server.read_config(), "CONTACT", "printer room")

    result = server.write_config(new)

    assert [(change.token, change.new) for change in result.changes] == [("CONTACT", "printer room")]
    assert (result.written, result.applied) == (True, True)
    assert "6000 CONTACT:printer room\n" in device.config
    assert device.actions == [DeviceAction.RESET]


def test_a_write_without_apply_leaves_the_device_running() -> None:
    device = _device()
    server = _server(device)

    result = server.write_config(with_value(server.read_config(), "CONTACT", "x"), apply=False)

    assert (result.written, result.applied) == (True, False)
    assert device.actions == []


def test_a_device_that_stores_something_else_is_reported_and_not_reset() -> None:
    device = _device()
    server = _server(device)
    new = with_value(server.read_config(), "CONTACT", "x")

    device.store_rewrites[render_config(new)] = device.config
    with pytest.raises(DeviceResponseError, match="stored a different configuration: CONTACT"):
        server.write_config(new)
    assert device.actions == []


def test_a_new_mail_password_is_not_mistaken_for_a_failed_write() -> None:
    device = _device()
    server = _server(device)

    result = server.write_config(with_value(server.read_config(), "MAIL_PAS", "newsecret"))

    assert result.written is True
    assert "4102 MAIL_PAS:newsecret\n" in device.config


# ---------------------------------------------------------------- waiting for a restart


def test_a_reset_waits_until_the_uptime_falls_back() -> None:
    device = _device()
    device.restart_after_reads = 3
    clock = _ManualClock()

    _server(device, clock=clock).reset()

    assert device.actions == [DeviceAction.RESET]
    assert clock.sleeps == [0.5, 0.5, 0.5]
    assert device.uptime_seconds < 5


def test_without_snmp_a_reset_cannot_be_confirmed() -> None:
    # Watching FTP go down missed the restart on the real device in both measured attempts, so
    # only the uptime counts as proof.
    device = _device()
    device.snmp_enabled = False
    clock = _ManualClock()

    with pytest.raises(
        DeviceUnavailableError, match="gave no SNMP answer within 120 s, so its restart could not be confirmed"
    ):
        _server(device, clock=clock).reset()
    assert device.actions == [DeviceAction.RESET]


def test_a_restart_is_confirmed_by_snmp_that_answers_only_after_it() -> None:
    # The ARP trick's case: no uptime is readable at the borrowed address before the restart.
    device = _device()
    device.snmp_silent_until_restart = True
    device.restart_after_reads = 2
    clock = _ManualClock()

    _server(device, clock=clock).reset()

    assert device.actions == [DeviceAction.RESET]
    assert device.uptime_seconds < 5


def test_a_restart_in_the_same_clock_tick_as_the_trigger_is_recognised() -> None:
    # Windows' monotonic clock ticks coarsely, so a fake that boots at once reads the same time as
    # the trigger: an uptime EQUAL to the time since the trigger is a restart too. Without one the
    # uptime would be longer, by however long the device ran before.
    clock = _ManualClock()
    device = FakeDevice(config=_device().config, psinf=_device().psinf, monitor=_device().monitor_text, clock=clock)

    _server(device, clock=clock).reset()

    assert device.actions == [DeviceAction.RESET]
    assert device.uptime_seconds <= 1.0


def test_a_restarted_device_is_waited_for_until_ftp_answers_again() -> None:
    device = _device()
    device.ftp_down_after_reset = 2
    clock = _ManualClock()

    _server(device, clock=clock).reset()

    assert device.actions == [DeviceAction.RESET]
    assert len(clock.sleeps) >= 2, "two failed FTP answers, each followed by a poll"


def test_a_device_that_does_not_restart_is_reported_after_the_deadline() -> None:
    device = _device()
    device.ignores_reset = True
    clock = _ManualClock()

    with pytest.raises(DeviceUnavailableError, match="did not restart within 120 s"):
        _server(device, clock=clock).reset()
    assert clock.now > 120


def test_a_reset_without_wait_returns_at_once() -> None:
    device = _device()
    device.ignores_reset = True
    clock = _ManualClock()

    _server(device, clock=clock).reset(wait=False)

    assert (device.actions, clock.sleeps) == ([DeviceAction.RESET], [])


def test_a_write_that_moves_the_device_waits_at_the_new_address() -> None:
    device = _device()
    server = _server(device)

    result = server.write_config(with_value(server.read_config(), "IP_ADDR", "192.0.2.99"))

    assert (result.applied, result.reachable_at) == (True, "192.0.2.99")
    assert device.actions == [DeviceAction.RESET]


def test_a_write_that_hands_the_address_to_dhcp_does_not_wait() -> None:
    device = _device()
    device.ignores_reset = True
    clock = _ManualClock()
    server = _server(device, clock=clock)

    result = server.write_config(with_value(server.read_config(), "DHCP_MODE", "Enable"))

    assert (result.applied, result.reachable_at) == (True, None)
    assert clock.sleeps == []


# ---------------------------------------------------------------- login


def test_a_write_the_device_refuses_is_retried_with_the_device_name_as_login() -> None:
    device = _device(login_for_writes="PS_EXAMPLE")

    _server(device).reset()

    assert device.actions == [DeviceAction.RESET]


def test_a_configured_login_that_is_refused_is_not_retried_with_another_one() -> None:
    device = _device(login_for_writes="PS_EXAMPLE")
    endpoint = DeviceEndpoint(host="192.0.2.52", login="WRONG")

    with pytest.raises(AuthenticationRequiredError):
        _server(device, endpoint=endpoint).reset()
    assert device.actions == []


def test_a_password_is_stored_and_then_needed_for_the_next_write() -> None:
    device = _device(login_for_writes="PS_EXAMPLE")
    server = _server(device)

    server.set_password(SecretStr("s3cret"))

    assert device.credential == "s3cret"
    with pytest.raises(AuthenticationRequiredError):
        server.reset()
    _server(device, endpoint=DeviceEndpoint(host="192.0.2.52", password=SecretStr("s3cret"))).reset()
    assert device.actions == [DeviceAction.RESET]


@pytest.mark.parametrize("password", ["x" * 20, "M\u00fcller", "tab\there"])
def test_a_password_the_device_cannot_store_is_refused_before_sending(password: str) -> None:
    device = _device()

    with pytest.raises(ValueError, match="at most 19 printable ASCII characters"):
        _server(device).set_password(SecretStr(password))
    assert device.credential == ""


# ---------------------------------------------------------------- confirmed actions


def _factory_default(server: PrintServer, name: str) -> None:
    server.factory_default(confirm_name=name)


def _clear_password(server: PrintServer, name: str) -> None:
    server.clear_password(confirm_name=name)


def _store_ip(server: PrintServer, name: str) -> None:
    server.store_ip(confirm_name=name)


_CONFIRMED_ACTIONS = [
    (_factory_default, DeviceAction.FACTORY_DEFAULT),
    (_clear_password, DeviceAction.CREDENTIAL_RESET),
    (_store_ip, DeviceAction.STORE_IP),
]


@pytest.mark.parametrize(("call", "action"), _CONFIRMED_ACTIONS)
@pytest.mark.parametrize("name", ["PS_EXAMPLE", "ps_example", " SC123456 "])
def test_a_dangerous_action_runs_when_the_device_name_is_repeated(
    call: Callable[[PrintServer, str], None], action: DeviceAction, name: str
) -> None:
    device = _device()

    call(_server(device), name)

    assert device.actions == [action]


@pytest.mark.parametrize(("call", "action"), _CONFIRMED_ACTIONS)
@pytest.mark.parametrize("name", ["", "PS_OTHER", "SC000000"])
def test_a_dangerous_action_without_the_right_name_does_nothing(
    call: Callable[[PrintServer, str], None], action: DeviceAction, name: str
) -> None:
    device = _device()

    with pytest.raises(ConfirmationRequiredError, match="PS_EXAMPLE or SC123456"):
        call(_server(device), name)
    assert action not in device.actions


# ---------------------------------------------------------------- printing


def test_an_lpd_job_goes_to_the_named_queue() -> None:
    device = _device()
    job = PrintJob(data=b"%!PS\n", name="report")

    _server(device).print_lpd("L2", job)

    assert device.lpd_jobs == [("L2", job)]
    assert _server(device).queue_state("L2") == "L2: 1 job(s)\n"


@pytest.mark.parametrize(("printer", "port"), [(1, 9100), (2, 9101), (3, 9102)])
def test_raw_data_goes_to_the_port_of_the_logical_printer(printer: int, port: int) -> None:
    device = _device()

    _server(device).print_raw(printer, b"\x1bE")

    assert device.raw_sends == [(port, b"\x1bE")]


def test_the_raw_port_base_is_configurable() -> None:
    device = _device()
    ports = DevicePorts(ftp=device, telnet=device, tftp=FakeTftp(device), lpd=device, raw=device, uptime=device)

    PrintServer(_ENDPOINT, ports, raw_port_base=9200).print_raw(2, b"x")

    assert device.raw_sends == [(9201, b"x")]


@pytest.mark.parametrize(
    ("printer", "data", "message"),
    [(1, b"", "without data"), (0, b"x", "has no RAW port"), (4, b"x", "only L1..L3 have one")],
)
def test_raw_printing_refuses_before_connecting(printer: int, data: bytes, message: str) -> None:
    device = _device()

    with pytest.raises(ValueError, match=message):
        _server(device).print_raw(printer, data)
    assert device.raw_sends == []
