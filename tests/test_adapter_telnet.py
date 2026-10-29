"""TelnetClient against a loopback server speaking the PS301's measured console dialect."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from fake_lpd_server import closed_port
from fake_telnet_server import GREETING, IDLE_MONITOR, FakeTelnetServer, TelnetBehaviour

from sercomm_printserver.adapters.telnet import TelnetClient
from sercomm_printserver.adapters.telnet.client import MONITOR_COMMAND
from sercomm_printserver.adapters.telnet.iac import IacStripper
from sercomm_printserver.domain.endpoint import DeviceEndpoint
from sercomm_printserver.domain.errors import DeviceResponseError, DeviceUnavailableError
from sercomm_printserver.domain.port_status import PortState, parse_monitor

if TYPE_CHECKING:
    from sercomm_printserver.application.ports import TelnetPort

pytestmark = pytest.mark.os_agnostic

#: Long enough that no healthy loopback exchange times out; the hang tests use _SHORT instead.
_PATIENT = 5.0
#: How long the client waits on a peer that deliberately never answers.
_SHORT = 0.3


def _endpoint(server: FakeTelnetServer, timeout: float = _PATIENT) -> DeviceEndpoint:
    return DeviceEndpoint(host="127.0.0.1", telnet_port=server.port, timeout=timeout)


def test_the_client_satisfies_the_telnet_port() -> None:
    port: TelnetPort = TelnetClient()

    assert callable(port.monitor)


def test_monitor_sends_monitor_and_exit_in_one_write_and_returns_the_blocks_without_the_echo() -> None:
    with FakeTelnetServer() as server:
        text = TelnetClient().monitor(_endpoint(server))

    assert server.received == b"monitor\r\nexit\r\n"
    assert text == IDLE_MONITOR.decode("ascii")
    assert [port.state for port in parse_monitor(text)] == [PortState.IDLE] * 3


def test_monitor_strips_negotiation_and_subnegotiation_and_unescapes_iac_iac() -> None:
    noisy = (
        b"\r\n(P1)STATE: Idle\r\n\xff\xfd\x18TYPE: Parallel\r\n"  # IAC DO TERMINAL-TYPE
        b"\xff\xfa\x18\x01\xff\xff\x00\xff\xf0"  # IAC SB TERMINAL-TYPE SEND <IAC IAC> 0 IAC SE
        b"PRINTER STATUS: Off\xff\xffline\r\n\r\n"  # IAC IAC: one literal 0xFF byte
        b"\xff\xf1"  # IAC NOP
    )

    with FakeTelnetServer(monitor_output=noisy) as server:
        text = TelnetClient().monitor(_endpoint(server))

    assert text == "\r\n(P1)STATE: Idle\r\nTYPE: Parallel\r\nPRINTER STATUS: Off\ufffdline\r\n\r\n"


@pytest.mark.parametrize("cut", range(1, len(GREETING)))
def test_the_stripper_gives_the_same_result_wherever_a_read_splits_a_sequence(cut: int) -> None:
    stream = GREETING + b"\xff\xfa\x18\x01\xff\xf0x\xff\xffy"
    stripper = IacStripper()

    pieces = stripper.feed(stream[:cut]) + stripper.feed(stream[cut:])

    assert pieces == b"\r\n\r\nWelcome to Print Server\r\n\r\nPS>x\xffy"


def test_a_device_that_never_prompts_is_a_response_error_and_gets_no_command() -> None:
    with (
        FakeTelnetServer(behaviour=TelnetBehaviour.NO_PROMPT) as server,
        pytest.raises(DeviceResponseError, match="no PS> prompt within") as caught,
    ):
        TelnetClient().monitor(_endpoint(server, timeout=_SHORT))

    assert "Welcome to Print Server" in str(caught.value)
    assert server.received == b""


def test_a_device_that_closes_before_the_prompt_is_a_response_error() -> None:
    with (
        FakeTelnetServer(behaviour=TelnetBehaviour.CLOSE_BEFORE_PROMPT) as server,
        pytest.raises(DeviceResponseError, match="closed before the PS> prompt"),
    ):
        TelnetClient().monitor(_endpoint(server))

    assert server.received == b""


def test_a_device_that_resets_before_the_prompt_is_unavailable() -> None:
    # The fake resets right after accept, and the client sends nothing it could wait for first.
    # On macOS that reset can reach connect() itself ("could not be reached") rather than the
    # first read ("broke the connection"); both are the same DeviceUnavailableError.
    address = re.escape("127.0.0.1:")
    with (
        FakeTelnetServer(behaviour=TelnetBehaviour.RESET_BEFORE_PROMPT) as server,
        pytest.raises(
            DeviceUnavailableError, match=rf"^{address}{server.port} (broke the connection|could not be reached): "
        ),
    ):
        TelnetClient().monitor(_endpoint(server))


def test_a_device_that_prompts_but_never_finishes_is_a_response_error() -> None:
    with (
        FakeTelnetServer(behaviour=TelnetBehaviour.PROMPT_THEN_HANG) as server,
        pytest.raises(DeviceResponseError, match="did not finish the monitor output"),
    ):
        TelnetClient().monitor(_endpoint(server, timeout=_SHORT))

    assert server.received == MONITOR_COMMAND


def test_a_device_that_floods_past_the_cap_is_a_response_error() -> None:
    with (
        FakeTelnetServer(behaviour=TelnetBehaviour.OVERSIZED, oversized_bytes=128 * 1024) as server,
        pytest.raises(DeviceResponseError, match="sent more than 65536 bytes"),
    ):
        TelnetClient().monitor(_endpoint(server))


def test_the_cap_counts_the_greeting_too() -> None:
    with FakeTelnetServer() as server, pytest.raises(DeviceResponseError, match="sent more than 16 bytes"):
        TelnetClient(max_response_bytes=16).monitor(_endpoint(server))


def test_a_refused_connection_is_unavailable_and_names_the_address() -> None:
    # A port nothing holds is refused on every OS; a bound-but-not-listening one times out on
    # macOS. The cause check keeps a timeout, which also reads "could not be reached", from
    # passing. The patient timeout covers Windows, which reports a refusal after about 2 s.
    port = closed_port()
    endpoint = DeviceEndpoint(host="127.0.0.1", telnet_port=port, timeout=_PATIENT)

    with pytest.raises(DeviceUnavailableError, match=re.escape(f"127.0.0.1:{port} could not be reached")) as caught:
        TelnetClient().monitor(endpoint)

    assert isinstance(caught.value.__cause__, ConnectionRefusedError)


def test_a_malformed_host_name_is_unavailable_not_a_raw_codec_error() -> None:
    with pytest.raises(DeviceUnavailableError, match=re.escape("bad..host:23 could not be reached")):
        TelnetClient().monitor(DeviceEndpoint(host="bad..host", timeout=_PATIENT))
