"""Use cases for one print server: read, configure, act, print.

:class:`PrintServer` is the library's working surface. Every action that changes the device is
its own method, and the three that can cut a device off the network (factory default, clearing
the password, storing the IP) refuse to run unless the caller repeats the device's name - the
library enforces it, not only the CLI.

The firmware serves ``CONFIG`` and ``PSINF`` without a login but may want one to write. When no
login is configured and the device answers 530, the call is retried once with the device's own
name, which is the login the vendor manuals prescribe.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypeVar

from pydantic import BaseModel

from ..domain import config_catalogue as cat
from ..domain.config_codec import ConfigChange, diff_config, parse_config, render_config
from ..domain.device_files import DeviceAction, ReadableFile, WritableFile
from ..domain.device_info import DeviceInfo, parse_firmware_reply, parse_psinf
from ..domain.errors import (
    AuthenticationRequiredError,
    ConfirmationRequiredError,
    DeviceResponseError,
    DeviceUnavailableError,
)
from ..domain.port_status import PortStatus, parse_monitor

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import SecretStr

    from ..domain.config_model import DeviceConfig
    from ..domain.endpoint import DeviceEndpoint, PrintJob
    from .ports import FtpPort, LpdPort, RawPort, TelnetPort, TftpPort, UptimePort

_T = TypeVar("_T")

#: The firmware stores at most 19 bytes of password (vendor manual: ``put PASSWORD``).
_PASSWORD_MAX: Final = 19
_RAW_LAST_PORT: Final = 65535
#: Parameters the device reads back masked with asterisks, so a read-back cannot verify them.
_READ_BACK_MASKED: Final = frozenset({cat.mail_line(2)})
#: How long a restart may take before waiting for it is given up.
_RESTART_TIMEOUT: Final = 120.0
_POLL_INTERVAL: Final = 0.5


@dataclass(frozen=True, slots=True)
class DevicePorts:
    """The protocol adapters one :class:`PrintServer` talks through."""

    ftp: FtpPort
    telnet: TelnetPort
    tftp: TftpPort
    lpd: LpdPort
    raw: RawPort
    uptime: UptimePort


class ConfigWriteResult(BaseModel, frozen=True, extra="forbid"):
    """What writing a configuration did.

    Attributes:
        changes: The parameters that differ from what the device had.
        written: Whether anything was uploaded (False when there was nothing to change).
        applied: Whether the device was restarted so the new configuration takes effect.
        reachable_at: Where the device answers afterwards: the new address when the write
            changed it, None when DHCP decides it (then nothing waited for the restart).
    """

    changes: tuple[ConfigChange, ...]
    written: bool
    applied: bool
    reachable_at: str | None


class PrintServer:
    """One SerComm print server, reached through injected protocol adapters.

    Args:
        endpoint: Address, credentials and timeout.
        ports: The protocol adapters.
        raw_port_base: TCP port of the RAW print port of logical printer ``L1``; ``Ln`` uses
            ``raw_port_base + n - 1``.
        sleep: Pause between checks while waiting for a restart (injected so tests do not wait).
        clock: Monotonic clock for that wait's deadline.
    """

    def __init__(
        self,
        endpoint: DeviceEndpoint,
        ports: DevicePorts,
        *,
        raw_port_base: int = 9100,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._endpoint = endpoint
        self._ports = ports
        self._raw_port_base = raw_port_base
        self._sleep = sleep
        self._clock = clock

    @property
    def endpoint(self) -> DeviceEndpoint:
        """The endpoint this instance talks to."""
        return self._endpoint

    # ------------------------------------------------------------------ reading

    def firmware_version(self) -> str:
        """Return the firmware version: from ``SYST``, or from ``PSINF`` when SYST garbles it.

        Firmware 6A10 answers ``SYST`` with random bytes where the version belongs; its
        ``PSINF`` report carries the version correctly.
        """
        try:
            return parse_firmware_reply(self._ports.ftp.system_reply(self._endpoint))
        except DeviceResponseError:
            return self.info().firmware_version

    def info(self) -> DeviceInfo:
        """Return the device's self-description (``PSINF``)."""
        return parse_psinf(self._read_text(ReadableFile.PSINF))

    def status(self) -> tuple[PortStatus, ...]:
        """Return the state of every physical port (Telnet ``monitor``)."""
        return parse_monitor(self._ports.telnet.monitor(self._endpoint))

    def read_config(self) -> DeviceConfig:
        """Return the device's configuration, typed."""
        return parse_config(self.read_config_text())

    def read_config_text(self) -> str:
        """Return the device's CONFIG file exactly as it sends it."""
        return self._read_text(ReadableFile.CONFIG)

    def queue_state(self, queue: str, *, long_format: bool = False) -> str:
        """Return the LPD queue state of ``queue`` (``L1``..``L8``); prints nothing."""
        return self._ports.lpd.queue_state(self._endpoint, queue, long_format=long_format)

    # ------------------------------------------------------------------ changing

    def plan_config(self, new: DeviceConfig) -> tuple[ConfigChange, ...]:
        """Return what writing ``new`` would change on the device, without writing."""
        return diff_config(self.read_config(), new)

    def write_config(self, new: DeviceConfig, *, apply: bool = True) -> ConfigWriteResult:
        """Upload ``new`` if it differs from the device's configuration, and verify the upload.

        Args:
            new: The complete configuration to store.
            apply: Restart the device afterwards so the configuration takes effect, and wait
                until it answers again - at its new address when the configuration moves it.

        Returns:
            What changed, whether it was written and applied, and where the device answers.

        Raises:
            DeviceResponseError: The device stored something other than what was sent.
        """
        current = self.read_config()
        changes = diff_config(current, new)
        if not changes:
            return ConfigWriteResult(changes=(), written=False, applied=False, reachable_at=self._endpoint.host)
        text = render_config(new)
        self._with_login(lambda endpoint: self._ports.ftp.store(endpoint, WritableFile.CONFIG, text.encode("ascii")))
        stored = [change for change in diff_config(new, self.read_config()) if change.number not in _READ_BACK_MASKED]
        if stored:
            raise DeviceResponseError(f"the device stored a different configuration: {_describe_changes(stored)}")
        if not apply:
            return ConfigWriteResult(changes=changes, written=True, applied=False, reachable_at=self._endpoint.host)
        target = self._endpoint_after(current, new)
        before = self._uptime(self._endpoint)
        self._trigger(DeviceAction.RESET)
        if target is not None:
            self._wait_for_restart(before, target)
        return ConfigWriteResult(
            changes=changes, written=True, applied=True, reachable_at=None if target is None else target.host
        )

    def reset(self, *, wait: bool = True) -> None:
        """Restart the device; a stored configuration takes effect.

        The device restarts about 5 s after the triggering session ends and keeps answering
        until then, so a call right after the trigger would land in the restart. With ``wait``
        this returns only once the device has restarted (its SNMP uptime fell back) and answers
        FTP again.

        Raises:
            DeviceUnavailableError: ``wait`` and the device did not come back in time.
        """
        before = self._uptime(self._endpoint)
        self._trigger(DeviceAction.RESET)
        if wait:
            self._wait_for_restart(before, self._endpoint)

    def set_password(self, password: SecretStr) -> None:
        """Set the login password (at most 19 bytes; the device name stays the login).

        The device reads the uploaded file up to a line end; without one it stores bytes past
        the upload and the intended password never matches, so the file ends with CRLF.
        """
        secret = password.get_secret_value()
        if not secret.isascii() or not secret.isprintable() or len(secret) > _PASSWORD_MAX:
            raise ValueError(f"the password must be at most {_PASSWORD_MAX} printable ASCII characters")
        content = f"{secret}\r\n".encode("ascii")
        self._with_login(lambda endpoint: self._ports.ftp.store(endpoint, WritableFile.LOGIN_CREDENTIAL, content))

    def clear_password(self, *, confirm_name: str) -> None:
        """Clear the login password. Needs the device's name as confirmation.

        The PS301 (firmware 6022) carries this out without any login, so a lost password never
        locks the device - and a password does not stop anyone on the network from clearing it.
        """
        self._confirm(confirm_name, action="clearing the password")
        self._trigger(DeviceAction.CREDENTIAL_RESET)

    def store_ip(self, *, confirm_name: str) -> None:
        """Store the address the device answers on now as its static IP. Needs the device's name."""
        self._confirm(confirm_name, action="storing the current IP address")
        self._trigger(DeviceAction.STORE_IP)

    def factory_default(self, *, confirm_name: str) -> None:
        """Restore factory settings: IP 0.0.0.0, no password. Needs the device's name.

        Afterwards the device looks for an address by DHCP, BOOTP and RARP and is no longer
        reachable at its old address.
        """
        self._confirm(confirm_name, action="restoring factory defaults")
        self._trigger(DeviceAction.FACTORY_DEFAULT)

    # ------------------------------------------------------------------ printing

    def print_lpd(self, queue: str, job: PrintJob) -> None:
        """Send ``job`` to the LPD queue ``queue`` (``L1``..``L8``)."""
        self._ports.lpd.submit(self._endpoint, queue, job)

    def print_raw(self, logical_printer: int, data: bytes) -> None:
        """Send ``data`` to the RAW port of logical printer ``logical_printer`` (1-based).

        A bare connect occupies the port for minutes on this firmware, so empty data is refused
        before anything is sent.
        """
        if not data:
            raise ValueError("refusing to open a RAW print port without data to send")
        port = self._raw_port_base + logical_printer - 1
        if logical_printer < 1 or port > _RAW_LAST_PORT:
            raise ValueError(f"logical printer {logical_printer} has no RAW port")
        self._ports.raw.send(self._endpoint, port, data)

    # ------------------------------------------------------------------ helpers

    def _read_text(self, name: ReadableFile) -> str:
        data = self._with_login(lambda endpoint: self._ports.ftp.retrieve(endpoint, name))
        return data.decode("ascii", errors="replace")

    def _endpoint_after(self, current: DeviceConfig, new: DeviceConfig) -> DeviceEndpoint | None:
        """Where the device answers once ``new`` is applied; None when DHCP will choose."""
        if new.tcp_ip.dhcp:
            return None
        if new.tcp_ip.ip_address == current.tcp_ip.ip_address:
            return self._endpoint
        return self._endpoint.model_copy(update={"host": str(new.tcp_ip.ip_address)})

    def _uptime(self, endpoint: DeviceEndpoint) -> float | None:
        try:
            return self._ports.uptime.uptime(endpoint)
        except (DeviceUnavailableError, DeviceResponseError):
            return None

    def _wait_for_restart(self, before: float | None, endpoint: DeviceEndpoint) -> None:
        deadline = self._clock() + _RESTART_TIMEOUT
        if before is not None:
            self._wait_until(
                deadline, lambda: self._restarted_since(before, endpoint), host=endpoint.host, what="restart"
            )
        else:
            # Without SNMP the restart shows only as FTP going away for a while.
            self._wait_until(deadline, lambda: not self._answers_ftp(endpoint), host=endpoint.host, what="go down")
        self._wait_until(deadline, lambda: self._answers_ftp(endpoint), host=endpoint.host, what="answer again")

    def _wait_until(self, deadline: float, condition: Callable[[], bool], *, host: str, what: str) -> None:
        while not condition():
            if self._clock() > deadline:
                raise DeviceUnavailableError(f"{host} did not {what} within {_RESTART_TIMEOUT:g} s")
            self._sleep(_POLL_INTERVAL)

    def _restarted_since(self, before: float, endpoint: DeviceEndpoint) -> bool:
        now = self._uptime(endpoint)
        return now is not None and now < before

    def _answers_ftp(self, endpoint: DeviceEndpoint) -> bool:
        try:
            self._ports.ftp.system_reply(endpoint)
        except (DeviceUnavailableError, DeviceResponseError):
            return False
        return True

    def _trigger(self, action: DeviceAction) -> None:
        self._with_login(lambda endpoint: self._ports.ftp.trigger(endpoint, action))

    def _confirm(self, confirm_name: str, *, action: str) -> None:
        info = self.info()
        names = {info.server_name.upper(), info.default_name.upper()}
        if confirm_name.strip().upper() not in names:
            raise ConfirmationRequiredError(
                f"{action} needs the device's name as confirmation ({info.server_name} or {info.default_name})"
            )

    def _with_login(self, call: Callable[[DeviceEndpoint], _T]) -> _T:
        try:
            return call(self._endpoint)
        except AuthenticationRequiredError:
            if self._endpoint.login:
                raise
        # PSINF is readable without a login on this family; its server name is the login.
        device = parse_psinf(self._ports.ftp.retrieve(self._endpoint, ReadableFile.PSINF).decode("ascii", "replace"))
        return call(self._endpoint.model_copy(update={"login": device.server_name}))


def _describe_changes(changes: list[ConfigChange]) -> str:
    return "; ".join(f"{change.token}: sent {change.old!r}, stored {change.new!r}" for change in changes)


__all__ = ["ConfigWriteResult", "DevicePorts", "PrintServer"]
