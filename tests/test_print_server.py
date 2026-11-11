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
    JobNotDrainedError,
    PortBusyError,
)
from sercomm_printserver.domain.port_health import PortHealth, PortVerdict
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


def _factory_reset_device() -> FakeDevice:
    # Measured 2026-10-27: after a factory reset BOX_NAME and the PSINF server name are empty, and
    # the FTP login the device takes is its default name.
    return FakeDevice(
        config=(_DUMPS / "CONFIG.txt").read_text(encoding="ascii").replace("BOX_NAME:PS_EXAMPLE", "BOX_NAME:"),
        psinf=(_DUMPS / "PSINF-factory.txt").read_text(encoding="ascii"),
        monitor="",
        login_for_writes="SC123456",
    )


def test_a_reset_device_without_a_server_name_is_logged_in_with_its_default_name() -> None:
    device = _factory_reset_device()

    _server(device).reset()

    assert device.actions == [DeviceAction.RESET]


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


@pytest.mark.parametrize(("call", "action"), _CONFIRMED_ACTIONS)
def test_an_empty_confirmation_does_not_match_the_empty_name_of_a_reset_device(
    call: Callable[[PrintServer, str], None], action: DeviceAction
) -> None:
    device = _factory_reset_device()

    with pytest.raises(ConfirmationRequiredError, match=r"needs the device's name as confirmation \( or SC123456\)"):
        call(_server(device), "")
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


# ---------------------------------------------------------------- printing, verified


def _monitor(*, p1: str = "Idle", p2: str = "Idle", sp: str = "Idle") -> str:
    blocks = [("P1", "Parallel", p1), ("P2", "Parallel", p2), ("SP", "Serial", sp)]
    return "\r\n\r\n".join(_monitor_block(port, kind, state) for port, kind, state in blocks) + "\r\n"


def _monitor_block(port: str, kind: str, state: str) -> str:
    head = f"({port})STATE: {state}\r\nTYPE: {kind}\r\nPRINTER STATUS: On-Line"
    return head if state == "Idle" else f"{head}\r\nBYTES SERVICED:          0\r\nOCCUPIED BY: Direct Socket"


def test_a_verified_raw_print_returns_once_the_routed_port_is_idle_again() -> None:
    device = _device()
    # Before the send, then twice busy, then drained. L3 is routed to SP in the dumped CONFIG.
    device.monitor_replies = [_monitor(), _monitor(sp="Printing"), _monitor(sp="Printing"), _monitor()]
    clock = _ManualClock()

    status = _server(device, clock=clock).print_raw_verified(3, b"\x1bE")

    assert device.raw_sends == [(9102, b"\x1bE")]
    assert (status.port.value, status.state) == ("SP", PortState.IDLE)
    assert device.monitor_replies == []
    assert clock.sleeps == [1.0, 1.0]


def test_a_verified_raw_print_ignores_a_port_the_printer_is_not_routed_to() -> None:
    device = _device()
    device.monitor_replies = [_monitor(p1="Printing"), _monitor(p1="Printing")]
    clock = _ManualClock()

    status = _server(device, clock=clock).print_raw_verified(3, b"x")

    assert status.port.value == "SP"
    assert clock.sleeps == []


def test_a_verified_raw_print_follows_the_routing_in_the_config() -> None:
    device = _device()
    device.config = device.config.replace("0100 L1_PROUT:P1", "0100 L1_PROUT:P2")
    device.monitor_replies = [_monitor(), _monitor()]

    assert _server(device).print_raw_verified(1, b"x").port.value == "P2"


def test_a_port_that_stays_busy_fails_the_verified_print_after_the_data_was_sent() -> None:
    device = _device()
    device.monitor_text = _monitor(sp="Printing")
    device.monitor_replies = [_monitor()]
    clock = _ManualClock()

    with pytest.raises(JobNotDrainedError) as caught:
        _server(device, clock=clock).print_raw_verified(3, b"x", timeout=2.5)

    assert device.raw_sends == [(9102, b"x")]
    assert str(caught.value) == (
        "192.0.2.52: the data was sent, but SP is wedged: it still reads Printing 2.5 s later "
        "(occupied by Direct Socket, 0 bytes serviced) and every RAW port routed there accepts a "
        "connection; `check --reset --yes` clears it"
    )
    # The last pause is cut to the deadline, and one more read decides at the deadline itself.
    assert clock.sleeps == [1.0, 1.0, 0.5]


def test_a_verified_raw_print_waits_for_a_busy_port_before_sending() -> None:
    device = _device()
    # Busy twice before the send, free, then busy once more after the send, then drained.
    device.monitor_replies = [
        _monitor(sp="Printing"),
        _monitor(sp="Printing"),
        _monitor(),
        _monitor(sp="Printing"),
        _monitor(),
    ]
    clock = _ManualClock()

    status = _server(device, clock=clock).print_raw_verified(3, b"x")

    assert status.state is PortState.IDLE
    assert device.raw_sends == [(9102, b"x")]
    assert device.monitor_replies == []
    assert clock.sleeps == [1.0, 1.0, 1.0]


def test_a_port_that_stays_busy_before_the_send_gets_nothing() -> None:
    device = _device()
    device.monitor_text = _monitor(sp="Printing")
    clock = _ManualClock()

    with pytest.raises(PortBusyError) as caught:
        _server(device, clock=clock).print_raw_verified(3, b"x", timeout=2.5)

    assert device.raw_sends == []
    assert str(caught.value) == (
        "192.0.2.52: nothing was sent, SP is wedged: it still reads Printing after 2.5 s "
        "(occupied by Direct Socket, 0 bytes serviced) and every RAW port routed there accepts a "
        "connection; `check --reset --yes` clears it"
    )
    assert clock.sleeps == [1.0, 1.0, 0.5]


def test_a_port_still_moving_bytes_is_reported_busy_without_a_probe() -> None:
    device = _device()
    device.monitor_text = _monitor(sp="Printing").replace("SERVICED:          0", "SERVICED:        512")
    clock = _ManualClock()

    with pytest.raises(PortBusyError) as caught:
        _server(device, clock=clock).print_raw_verified(3, b"x", timeout=1.0)

    assert str(caught.value) == (
        "192.0.2.52: nothing was sent, SP is still Printing after 1 s "
        "(occupied by Direct Socket, 512 bytes serviced); a restart clears a stuck port"
    )
    assert device.raw_probes == []


def test_each_wait_of_a_verified_print_gets_the_whole_timeout() -> None:
    device = _device()
    device.monitor_replies = [_monitor(sp="Printing"), _monitor(sp="Printing"), _monitor()]
    device.monitor_text = _monitor(sp="Printing")
    clock = _ManualClock()

    with pytest.raises(JobNotDrainedError):
        _server(device, clock=clock).print_raw_verified(3, b"x", timeout=2.0)

    # Two pauses before the send, then two more after it: the first wait did not use up the second.
    assert device.raw_sends == [(9102, b"x")]
    assert clock.sleeps == [1.0, 1.0, 1.0, 1.0]


def test_one_unanswered_status_read_before_the_send_does_not_stop_the_print() -> None:
    device = _device()
    device.monitor_replies = [DeviceUnavailableError("no answer"), _monitor(), _monitor()]

    assert _server(device).print_raw_verified(3, b"x").port.value == "SP"
    assert device.raw_sends == [(9102, b"x")]


def test_one_unanswered_status_read_does_not_fail_a_verified_print() -> None:
    device = _device()
    device.monitor_replies = [_monitor(), DeviceUnavailableError("no answer"), _monitor()]

    assert _server(device).print_raw_verified(3, b"x").port.value == "SP"


def test_a_port_that_cannot_be_read_any_more_fails_saying_the_data_was_sent() -> None:
    device = _device()
    device.monitor_replies = [_monitor(), *[DeviceUnavailableError("no answer")] * 5]

    # Not a DeviceUnavailableError: a caller branching on that type reads it as "nothing was sent",
    # sends the job again and prints it twice.
    with pytest.raises(JobNotDrainedError, match=r"the data was sent, but SP could not be read 2 s later: no answer"):
        _server(device).print_raw_verified(3, b"x", timeout=2.0)
    assert device.raw_sends == [(9102, b"x")]


def test_a_port_unreadable_until_the_deadline_is_unavailable_with_nothing_sent() -> None:
    device = _device()
    device.monitor_replies = [DeviceUnavailableError("no answer")] * 5

    with pytest.raises(DeviceUnavailableError, match=r"nothing was sent, SP could not be read for 2 s: no answer"):
        _server(device).print_raw_verified(3, b"x", timeout=2.0)
    assert device.raw_sends == []


def test_a_routed_port_the_status_does_not_list_is_refused_before_sending() -> None:
    device = _device()
    device.monitor_text = "(P1)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Offline\r\n"

    with pytest.raises(DeviceResponseError, match=r"L3 is routed to SP, which the status does not list"):
        _server(device).print_raw_verified(3, b"x")
    assert device.raw_sends == []


@pytest.mark.parametrize(
    ("printer", "data", "message"),
    [(1, b"", "without data"), (0, b"x", "has no RAW port"), (4, b"x", "only L1..L3 have one")],
)
def test_a_verified_raw_print_refuses_bad_input_before_reading_the_device(
    printer: int, data: bytes, message: str
) -> None:
    device = _device()
    device.reachable = False

    with pytest.raises(ValueError, match=message):
        _server(device).print_raw_verified(printer, data)


# ---------------------------------------------------------------- the drain wait


def test_a_raw_print_routed_to_the_serial_port_waits_for_its_link() -> None:
    # L3 is routed to SP in the dumped CONFIG, which runs 9600 8N1: 960 bytes per second.
    device = _device()

    _server(device).print_raw(3, b"x")

    [drain] = device.raw_drains
    assert drain is not None
    assert drain.bytes_per_second == 960.0


def test_the_drain_follows_the_configured_baud_rate() -> None:
    device = _device()
    device.config = device.config.replace("0030 BAUDRATE:9600", "0030 BAUDRATE:2400")

    _server(device).print_raw(3, b"x")

    [drain] = device.raw_drains
    assert drain is not None
    assert drain.bytes_per_second == 240.0


def test_a_raw_print_routed_to_a_parallel_port_does_not_wait() -> None:
    device = _device()

    _server(device).print_raw(1, b"x")

    assert device.raw_drains == [None]


def test_a_verified_raw_print_waits_for_the_link_too() -> None:
    device = _device()
    device.monitor_replies = [_monitor(), _monitor()]

    _server(device).print_raw_verified(3, b"x")

    [drain] = device.raw_drains
    assert drain is not None
    assert drain.bytes_per_second == 960.0


def test_a_raw_print_that_cannot_read_the_routing_sends_nothing() -> None:
    device = _device()
    device.reachable = False

    with pytest.raises(DeviceUnavailableError):
        _server(device).print_raw(3, b"x")
    assert device.raw_sends == []


# ---------------------------------------------------------------- check


def _verdicts(ports: tuple[PortHealth, ...]) -> dict[str, PortVerdict]:
    return {health.status.port.value: health.verdict for health in ports}


def test_a_device_with_every_port_idle_checks_clean_without_reading_the_config() -> None:
    device = _device()
    device.monitor_text = _monitor()

    result = _server(device).check()

    assert _verdicts(result.ports) == {"P1": PortVerdict.IDLE, "P2": PortVerdict.IDLE, "SP": PortVerdict.IDLE}
    assert result.wedged is False
    assert device.retrieved == []
    assert device.raw_probes == []


def test_a_stuck_direct_socket_port_that_accepts_every_probe_is_wedged() -> None:
    device = _device()
    device.monitor_text = _monitor(sp="Printing")

    result = _server(device).check()

    assert _verdicts(result.ports)["SP"] is PortVerdict.WEDGED
    assert result.wedged is True
    # L3 (9102) is the only one of L1..L3 routed to SP; L6 is too, but has no RAW port.
    assert device.raw_probes == [9102]
    assert device.raw_sends == []


def test_a_port_another_client_holds_refuses_the_probe_and_reads_held() -> None:
    device = _device()
    device.monitor_text = _monitor(sp="Printing")
    device.raw_refusing = {9102}

    result = _server(device).check()

    assert _verdicts(result.ports)["SP"] is PortVerdict.HELD
    assert result.wedged is False


def test_one_refusing_raw_port_of_several_routed_there_reads_held() -> None:
    # Only a port every probe got into counts as wedged, so a live job is never called one.
    device = _device()
    device.config = device.config.replace("0100 L1_PROUT:P1", "0100 L1_PROUT:SP")
    device.monitor_text = _monitor(sp="Printing")
    device.raw_refusing = {9102}

    assert _verdicts(_server(device).check().ports)["SP"] is PortVerdict.HELD


def test_every_raw_port_routed_to_a_wedged_port_is_probed() -> None:
    device = _device()
    device.config = device.config.replace("0100 L1_PROUT:P1", "0100 L1_PROUT:SP")
    device.monitor_text = _monitor(sp="Printing")

    assert _verdicts(_server(device).check().ports)["SP"] is PortVerdict.WEDGED
    assert device.raw_probes == [9100, 9102]


def test_a_candidate_no_raw_port_is_routed_to_is_reported_unprobed() -> None:
    device = _device()
    device.monitor_text = _monitor(p2="Printing")
    device.config = device.config.replace("0120 L2_PROUT:P2", "0120 L2_PROUT:P1")

    result = _server(device).check()

    assert _verdicts(result.ports)["P2"] is PortVerdict.UNPROBED
    assert result.wedged is False
    assert device.raw_probes == []


@pytest.mark.parametrize(
    "block",
    [
        "BYTES SERVICED:        512\r\nOCCUPIED BY: Direct Socket",
        "BYTES SERVICED:          0\r\nOCCUPIED BY: LPD",
    ],
)
def test_a_port_moving_bytes_or_held_by_another_protocol_is_printing(block: str) -> None:
    device = _device()
    head = "(SP)STATE: Printing\r\nTYPE: Serial\r\nPRINTER STATUS: On-Line"
    device.monitor_text = f"(P1)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: On-Line\r\n\r\n{head}\r\n{block}\r\n"

    result = _server(device).check()

    assert _verdicts(result.ports)["SP"] is PortVerdict.PRINTING
    assert device.raw_probes == []


def test_reset_if_wedged_restarts_and_checks_again() -> None:
    device = _device()
    device.restart_after_reads = 1
    device.monitor_replies = [_monitor(sp="Printing"), _monitor()]

    result = _server(device).reset_if_wedged()

    assert device.actions == [DeviceAction.RESET]
    assert result.restarted is True
    assert _verdicts(result.before)["SP"] is PortVerdict.WEDGED
    assert _verdicts(result.ports)["SP"] is PortVerdict.IDLE
    assert result.wedged is False


def test_reset_if_wedged_leaves_a_device_alone_when_nothing_is_wedged() -> None:
    device = _device()
    device.monitor_text = _monitor(sp="Printing")
    device.raw_refusing = {9102}

    result = _server(device).reset_if_wedged()

    assert device.actions == []
    assert result.restarted is False
    assert result.before == ()
    assert _verdicts(result.ports)["SP"] is PortVerdict.HELD


def test_a_wedge_that_survives_the_restart_is_still_reported() -> None:
    device = _device()
    device.restart_after_reads = 1
    device.monitor_text = _monitor(sp="Printing")

    result = _server(device).reset_if_wedged()

    assert result.restarted is True
    assert result.wedged is True


def test_a_verified_print_names_a_wedge_in_its_refusal() -> None:
    device = _device()
    device.monitor_text = _monitor(sp="Printing")

    with pytest.raises(PortBusyError, match=r"SP is wedged.*check --reset --yes"):
        _server(device, clock=_ManualClock()).print_raw_verified(3, b"x", timeout=1.0)
    assert device.raw_sends == []


def test_a_verified_print_names_another_client_in_its_refusal() -> None:
    device = _device()
    device.monitor_text = _monitor(sp="Printing")
    device.raw_refusing = {9102}

    with pytest.raises(PortBusyError, match=r"another client holds it"):
        _server(device, clock=_ManualClock()).print_raw_verified(3, b"x", timeout=1.0)


def test_a_verified_print_names_a_wedge_left_after_its_own_send() -> None:
    device = _device()
    device.monitor_replies = [_monitor()]
    device.monitor_text = _monitor(sp="Printing")

    with pytest.raises(JobNotDrainedError, match=r"the data was sent, but SP is wedged"):
        _server(device, clock=_ManualClock()).print_raw_verified(3, b"x", timeout=1.0)
