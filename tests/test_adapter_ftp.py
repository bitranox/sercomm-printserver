"""FtpClient against a loopback fake that speaks the PS301's FTP dialect.

Every test runs a real FTP conversation over 127.0.0.1 and asserts the exact command lines the
fake received, so the client is checked for what it sends (active mode, no PASV/PWD/NOOP, login
only when configured), not only for what it returns.
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

import pytest
from fake_ftp_server import FakeFtpBehaviour, FakeFtpServer, closed_port

from sercomm_printserver.adapters.ftp import FtpClient
from sercomm_printserver.adapters.ftp.client import MAX_FILE_BYTES
from sercomm_printserver.domain.device_files import DeviceAction, ReadableFile, WritableFile
from sercomm_printserver.domain.endpoint import DeviceEndpoint
from sercomm_printserver.domain.errors import (
    AuthenticationRequiredError,
    DeviceResponseError,
    DeviceUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sercomm_printserver.application.ports import FtpPort

pytestmark = pytest.mark.os_agnostic

CONFIG_BYTES = b"BOX_NAME PS_TEST\nIP_ADDR 192.0.2.52\n\nSUBNET_MASK 255.255.255.0\n"
PSINF_BYTES = b"Device Name : PS_TEST\r\nFirmware : 6022\r\n\x0c\r"
LOGIN = "PS_TEST"
PASSWORD = "s3cr3t-pw"


class FakeTime:
    """Injected clock and sleep: records every wait and advances the clock by it."""

    def __init__(self, on_sleep: Callable[[int], None] | None = None) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self._on_sleep = on_sleep

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if self._on_sleep is not None:
            self._on_sleep(len(self.sleeps))


def _endpoint(port: int, *, login: str = "", password: str = "", timeout: float = 5.0) -> DeviceEndpoint:
    return DeviceEndpoint.model_validate(
        {"host": "127.0.0.1", "ftp_port": port, "login": login, "password": password, "timeout": timeout}
    )


def _verbs(server: FakeFtpServer) -> list[str]:
    return [line.split(" ", 1)[0] for line in server.commands]


def _client(clock: FakeTime | None = None) -> FtpClient:
    fake = clock or FakeTime()
    return FtpClient(sleep=fake.sleep, clock=fake.monotonic)


def test_ftp_client_satisfies_the_port() -> None:
    port: FtpPort = FtpClient()
    assert isinstance(port, FtpClient)


def test_system_reply_never_logs_in_even_with_a_login_configured() -> None:
    with FakeFtpServer(FakeFtpBehaviour()) as server:
        reply = _client().system_reply(_endpoint(server.port, login=LOGIN, password=PASSWORD))
    assert reply == "215 Print Server FW 6022"
    assert server.commands == ["SYST", "QUIT"]


def test_system_reply_refuses_a_reply_other_than_215() -> None:
    with (
        FakeFtpServer(FakeFtpBehaviour(replies={"SYST": "200 Command OK."})) as server,
        pytest.raises(DeviceResponseError, match="200 Command OK"),
    ):
        _client().system_reply(_endpoint(server.port))


def test_retrieve_config_returns_exact_bytes_in_active_binary_mode() -> None:
    with FakeFtpServer(FakeFtpBehaviour(files={"CONFIG": CONFIG_BYTES})) as server:
        data = _client().retrieve(_endpoint(server.port), ReadableFile.CONFIG)
    assert data == CONFIG_BYTES
    assert _verbs(server) == ["TYPE", "PORT", "RETR", "QUIT"]
    assert server.commands[0] == "TYPE I"
    assert server.commands[2] == "RETR CONFIG"


def test_retrieve_psinf_keeps_crlf_and_the_trailing_form_feed() -> None:
    with FakeFtpServer(FakeFtpBehaviour(files={"PSINF": PSINF_BYTES})) as server:
        data = _client().retrieve(_endpoint(server.port), ReadableFile.PSINF)
    assert data == PSINF_BYTES
    assert server.commands[2] == "RETR PSINF"


def test_retrieve_logs_in_first_when_a_login_is_configured() -> None:
    behaviour = FakeFtpBehaviour(files={"CONFIG": CONFIG_BYTES}, credentials=(LOGIN, PASSWORD))
    with FakeFtpServer(behaviour) as server:
        data = _client().retrieve(_endpoint(server.port, login=LOGIN, password=PASSWORD), ReadableFile.CONFIG)
    assert data == CONFIG_BYTES
    assert server.commands[:2] == [f"USER {LOGIN}", f"PASS {PASSWORD}"]


def test_login_skips_pass_when_user_alone_is_accepted() -> None:
    behaviour = FakeFtpBehaviour(files={"CONFIG": CONFIG_BYTES}, replies={"USER": "230 User logged in."})
    with FakeFtpServer(behaviour) as server:
        _client().retrieve(_endpoint(server.port, login=LOGIN), ReadableFile.CONFIG)
    assert _verbs(server) == ["USER", "TYPE", "PORT", "RETR", "QUIT"]


def test_login_answered_with_an_unexpected_code_is_a_response_error() -> None:
    with (
        FakeFtpServer(FakeFtpBehaviour(replies={"PASS": "332 Need account for login."})) as server,
        pytest.raises(DeviceResponseError, match="332 Need account"),
    ):
        _client().retrieve(_endpoint(server.port, login=LOGIN), ReadableFile.CONFIG)


def test_store_logs_in_and_uploads_the_exact_bytes() -> None:
    upload = b"BOX_NAME PS_NEW\r\nraw \x00\xff bytes\n"
    with FakeFtpServer(FakeFtpBehaviour(credentials=(LOGIN, PASSWORD))) as server:
        _client().store(_endpoint(server.port, login=LOGIN, password=PASSWORD), WritableFile.CONFIG, upload)
    assert server.uploads == {"CONFIG": upload}
    assert server.commands[:3] == [f"USER {LOGIN}", f"PASS {PASSWORD}", "TYPE I"]
    assert _verbs(server)[3:] == ["PORT", "STOR", "QUIT"]
    assert server.commands[4] == "STOR CONFIG"


def test_store_of_the_credential_file_uses_its_device_name() -> None:
    with FakeFtpServer(FakeFtpBehaviour()) as server:
        _client().store(_endpoint(server.port), WritableFile.LOGIN_CREDENTIAL, b"newpass")
    assert server.uploads == {"PASSWORD": b"newpass"}


def test_trigger_succeeds_on_a_completed_empty_transfer() -> None:
    with FakeFtpServer(FakeFtpBehaviour()) as server:
        _client().trigger(_endpoint(server.port), DeviceAction.STORE_IP)
    assert _verbs(server) == ["TYPE", "PORT", "RETR", "QUIT"]
    assert server.commands[2] == "RETR SETIP"


def test_trigger_succeeds_when_the_device_drops_the_connection_after_retr() -> None:
    with FakeFtpServer(FakeFtpBehaviour(drop_after="RETR")) as server:
        _client().trigger(_endpoint(server.port), DeviceAction.RESET)
    assert server.commands[-1] == "RETR RESET"
    assert "QUIT" not in server.commands


def test_trigger_fails_when_the_connection_drops_before_retr_was_sent() -> None:
    with (
        FakeFtpServer(FakeFtpBehaviour(drop_after="TYPE")) as server,
        pytest.raises(DeviceUnavailableError, match=f"127.0.0.1:{server.port}"),
    ):
        _client().trigger(_endpoint(server.port), DeviceAction.RESET)
    assert "RETR RESET" not in server.commands


def test_trigger_refused_by_the_device_is_a_response_error() -> None:
    with (
        FakeFtpServer(FakeFtpBehaviour(replies={"RETR": "550 File not found."})) as server,
        pytest.raises(DeviceResponseError, match="550 File not found"),
    ):
        _client().trigger(_endpoint(server.port), DeviceAction.FACTORY_DEFAULT)
    assert "RETR DEFAULTC" in server.commands


def test_530_without_login_raises_authentication_required() -> None:
    behaviour = FakeFtpBehaviour(files={"CONFIG": CONFIG_BYTES}, credentials=(LOGIN, PASSWORD))
    with FakeFtpServer(behaviour) as server, pytest.raises(AuthenticationRequiredError, match="530 Not logged in"):
        _client().retrieve(_endpoint(server.port), ReadableFile.CONFIG)
    assert not any(line.startswith(("USER", "PASS")) for line in server.commands)


def test_the_ps301s_531_invalid_password_is_an_authentication_refusal() -> None:
    behaviour = FakeFtpBehaviour(replies={"PASS": "531 Invalid password."})
    with FakeFtpServer(behaviour) as server, pytest.raises(AuthenticationRequiredError, match="531 Invalid password"):
        _client().store(_endpoint(server.port, login=LOGIN, password=PASSWORD), WritableFile.CONFIG, b"x")
    assert f"PASS {PASSWORD}" in server.commands


def test_wrong_password_never_appears_in_the_error_or_its_traceback() -> None:
    behaviour = FakeFtpBehaviour(credentials=(LOGIN, "other"), echo_password_on_refusal=True)
    with FakeFtpServer(behaviour) as server, pytest.raises(AuthenticationRequiredError) as caught:
        _client().store(_endpoint(server.port, login=LOGIN, password=PASSWORD), WritableFile.CONFIG, b"x")
    # The fake really echoed it, so the absence below is the client's doing.
    assert f"PASS {PASSWORD}" in server.commands
    rendered = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert PASSWORD not in str(caught.value)
    assert PASSWORD not in repr(caught.value)
    assert PASSWORD not in rendered
    assert "530 Login incorrect for password ***" in str(caught.value)


@pytest.mark.parametrize(
    "password",
    ["pw\r\nDELE CONFIG", "pw\nDELE CONFIG", "pw" + chr(0x20AC) + "DELE CONFIG"],
    ids=["crlf", "lf", "euro-sign"],
)
def test_an_unsendable_password_is_refused_before_anything_is_sent(password: str) -> None:
    with (
        FakeFtpServer(FakeFtpBehaviour()) as server,
        pytest.raises(AuthenticationRequiredError, match="line break or a character FTP cannot send") as caught,
    ):
        _client().retrieve(_endpoint(server.port, login=LOGIN, password=password), ReadableFile.CONFIG)
    assert "DELE" not in str(caught.value)
    assert server.commands == ["QUIT"]


def test_a_500_reply_is_a_response_error_quoting_the_reply() -> None:
    with (
        FakeFtpServer(FakeFtpBehaviour(replies={"RETR": "500 Invalid command."})) as server,
        pytest.raises(DeviceResponseError, match=r"127\.0\.0\.1:\d+ answered '500 Invalid command\.'"),
    ):
        _client().retrieve(_endpoint(server.port), ReadableFile.CONFIG)


def test_a_banner_other_than_220_is_a_response_error() -> None:
    with (
        FakeFtpServer(FakeFtpBehaviour(banner="120 Service ready in 5 minutes.")) as server,
        pytest.raises(DeviceResponseError, match="120 Service ready"),
    ):
        _client().system_reply(_endpoint(server.port))
    assert server.commands == []


def test_a_file_larger_than_the_bound_is_refused() -> None:
    with (
        FakeFtpServer(FakeFtpBehaviour(files={"CONFIG": b"x" * (MAX_FILE_BYTES + 1)})) as server,
        pytest.raises(DeviceResponseError, match="sent more than"),
    ):
        _client().retrieve(_endpoint(server.port), ReadableFile.CONFIG)


def test_refused_connects_are_retried_with_doubling_backoff_until_the_device_listens() -> None:
    server = FakeFtpServer(FakeFtpBehaviour(files={"CONFIG": CONFIG_BYTES}), listening=False)

    def listen_after_second_wait(waits: int) -> None:
        if waits == 2:
            server.begin_listening()

    clock = FakeTime(on_sleep=listen_after_second_wait)
    with server:
        data = _client(clock).retrieve(_endpoint(server.port), ReadableFile.CONFIG)
    assert data == CONFIG_BYTES
    assert clock.sleeps == [0.05, 0.1]
    assert server.sessions == 1


def test_refusal_past_the_deadline_raises_device_unavailable() -> None:
    clock = FakeTime()
    with (
        FakeFtpServer(FakeFtpBehaviour(), listening=False) as server,
        pytest.raises(DeviceUnavailableError, match=f"127.0.0.1:{server.port} refused the connection for 2 s"),
    ):
        _client(clock).system_reply(_endpoint(server.port))
    assert clock.sleeps == [0.05, 0.1, 0.2, 0.4, 0.4, 0.4, 0.4]
    assert server.sessions == 0


def test_nothing_listening_raises_device_unavailable_naming_the_address() -> None:
    port = closed_port()
    with pytest.raises(DeviceUnavailableError, match=f"127.0.0.1:{port}"):
        _client().system_reply(_endpoint(port))


def test_a_silent_device_times_out_without_any_retry() -> None:
    clock = FakeTime()
    # 0.2 s is the protocol timeout under test, not a wait for the server.
    with (
        FakeFtpServer(FakeFtpBehaviour(send_banner=False)) as server,
        pytest.raises(DeviceUnavailableError, match=r"did not answer within 0\.2 s"),
    ):
        _client(clock).system_reply(_endpoint(server.port, timeout=0.2))
    assert clock.sleeps == []
