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

from pydantic import BaseModel, computed_field

from ..domain import config_catalogue as cat
from ..domain.config_codec import ConfigChange, diff_config, parse_config, render_config
from ..domain.device_files import DeviceAction, ReadableFile, WritableFile
from ..domain.device_info import DeviceInfo, parse_firmware_reply, parse_psinf
from ..domain.errors import (
    AuthenticationRequiredError,
    ConfirmationRequiredError,
    DeviceResponseError,
    DeviceUnavailableError,
    JobNotDrainedError,
    PortBusyError,
)
from ..domain.link import link_drain_for
from ..domain.port_health import PortHealth, PortVerdict, is_wedge_candidate, probed_verdict, unprobed_verdict
from ..domain.port_status import PortState, PortStatus, parse_monitor
from ..domain.print_data import PrintData

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import SecretStr

    from ..domain.config_model import DeviceConfig
    from ..domain.config_types import PortId
    from ..domain.endpoint import DeviceEndpoint, PrintJob
    from .ports import FtpPort, LpdPort, RawPort, TelnetPort, TftpPort, UptimePort

_T = TypeVar("_T")

#: The firmware stores at most 19 bytes of password (vendor manual: ``put PASSWORD``).
_PASSWORD_MAX: Final = 19
_RAW_LAST_PORT: Final = 65535
#: Only L1..L3 have a RAW port (measured on a PS301, firmware 6022: 9103 is closed); the vendor
#: manuals give the same three, as DSI sockets 4010/4020/4030.
_RAW_LAST_PRINTER: Final = 3
#: Parameters the device reads back masked with asterisks, so a read-back cannot verify them.
#: Re-uploading the mask is safe: the device keeps the stored value when it receives it.
_READ_BACK_MASKED: Final = frozenset({cat.mail_line(cat.MailField.PASSWORD)})
#: How long a restart may take before waiting for it is given up.
_RESTART_TIMEOUT: Final = 120.0
_POLL_INTERVAL: Final = 0.5
#: How long a port may stay busy before and after a verified RAW print: a short label drains in well
#: under a second, and the printer's own handling gets the rest. A long job needs its own value.
DEFAULT_VERIFY_TIMEOUT: Final = 30.0
#: Pause between status reads of a verified print. Each read is a Telnet session of about 1.1 s
#: (measured on a PS301, FW 6022), so a shorter pause would keep the device's Telnet side busy.
_VERIFY_POLL_INTERVAL: Final = 1.0


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


class CheckResult(BaseModel, frozen=True, extra="forbid"):
    """What :meth:`PrintServer.check` or :meth:`PrintServer.reset_if_wedged` found.

    Attributes:
        ports: Every port's health; after a restart, as read after it.
        restarted: Whether the device was restarted because a port was wedged.
        before: Every port's health before that restart; empty when there was none.
    """

    ports: tuple[PortHealth, ...]
    restarted: bool = False
    before: tuple[PortHealth, ...] = ()

    @computed_field
    @property
    def wedged(self) -> bool:
        """Whether a port is (still) wedged."""
        return any(health.verdict is PortVerdict.WEDGED for health in self.ports)


class PrintServer:
    """One SerComm print server, reached through injected protocol adapters.

    Args:
        endpoint: Address, credentials and timeout.
        ports: The protocol adapters.
        raw_port_base: TCP port of the RAW print port of logical printer ``L1``; ``L2`` and
            ``L3`` use the next two ports.
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

    def check(self) -> CheckResult:
        """Tell every busy port apart: printing, held by a client, or wedged.

        One monitor read. Only a port reading ``Printing`` / ``Direct Socket`` / 0 bytes serviced
        costs more: the configuration is read, and each RAW port (L1..L3) routed there gets a bare
        connect with no data. A wedged port accepts every one; a port a client holds refuses
        (measured on a PS301, FW 6022). Not detectable this way: a RAW port that refuses every
        connect while the monitor reads Idle, and an idle port whose printer does not answer.
        """
        return CheckResult(ports=self._health(self.status()))

    def reset_if_wedged(self) -> CheckResult:
        """Run :meth:`check`; if a port is wedged, restart the device, wait for it, and check again.

        A restart is the only measured cure (12 of 12; waiting a minute, a clean connect or a
        printer reset cleared none of 9). It restarts every port, so it runs only on a wedge.

        Raises:
            DeviceUnavailableError: The device did not come back from the restart in time.
        """
        found = self.check()
        if not found.wedged:
            return found
        self.reset(wait=True)
        return CheckResult(ports=self.check().ports, restarted=True, before=found.ports)

    def read_config(self) -> DeviceConfig:
        """Return the device's configuration, typed."""
        return parse_config(self.read_config_text())

    def read_config_text(self) -> str:
        """Return the device's CONFIG file exactly as it sends it."""
        return self._read_text(ReadableFile.CONFIG)

    def queue_state(self, queue: str, *, long_format: bool = False) -> str:
        """Return the LPD queue state of ``queue`` (``L1``..``L8``); sends no print data."""
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
            DeviceResponseError: The device stored something other than what was sent. A PS301
                has done this rarely and stored the next upload right, so call again; there is
                no automatic retry, which would hide a device that really rewrites a value.
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
        triggered = self._clock()
        self._trigger(DeviceAction.RESET)
        if target is not None:
            self._wait_for_restart(triggered, target)
        return ConfigWriteResult(
            changes=changes, written=True, applied=True, reachable_at=None if target is None else target.host
        )

    def reset(self, *, wait: bool = True) -> None:
        """Restart the device; a stored configuration takes effect.

        The device restarts about 5 s after the triggering session ends and keeps answering
        until then, so a call right after the trigger would land in the restart. With ``wait``
        this returns only once the device has restarted (its SNMP uptime is no longer than the
        time since the trigger) and answers FTP again.

        Raises:
            DeviceUnavailableError: ``wait`` and the device did not come back in time, or never
                answered SNMP, so its restart could not be confirmed.
        """
        triggered = self._clock()
        self._trigger(DeviceAction.RESET)
        if wait:
            self._wait_for_restart(triggered, self._endpoint)

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
        """Restore factory settings: no password, an empty name, IP 0.0.0.0 with DHCP on. Needs the device's name.

        Returns once the reset is triggered, without waiting. The device restarts and takes an
        address by DHCP (the vendor manuals add BOOTP and RARP), which may be its old one (measured
        on FW 6022); without a DHCP server it has no usable address and is reached with the ARP
        trick. Its login is then its default name.
        """
        self._confirm(confirm_name, action="restoring factory defaults")
        self._trigger(DeviceAction.FACTORY_DEFAULT)

    # ------------------------------------------------------------------ printing

    def print_lpd(self, queue: str, job: PrintJob) -> int:
        """Send ``job`` to the LPD queue ``queue`` (``L1``..``L8``); return the bytes of data sent.

        Data of unknown size (a pipe) is spooled to a temporary file first, because LPD sends the
        size ahead of the data.
        """
        return self._ports.lpd.submit(self._endpoint, queue, job)

    def print_raw(self, logical_printer: int, data: PrintData | bytes) -> int:
        """Send ``data`` to the RAW port of logical printer ``logical_printer`` (1-3).

        The RAW port belongs to the logical printer, not to a physical port: the data goes to
        whichever physical port the printer is routed to (``Ln_PROUT``), as an LPD job would.
        A job stays queued as "Printing / Direct Socket" while no printer takes it, so empty data
        is refused before anything is sent.

        The configuration is read first: a printer on the serial port gets its data at the
        port's baud rate, and a RAW connection opened before the device has passed a job on
        loses its data and wedges the port. So the connection stays open until the job has
        crossed the serial link, plus a margin; a parallel or USB printer gets no wait.

        The data is sent piece by piece, so a large file never sits in memory whole. For a
        stream of unknown size (a pipe) the first piece is read up front, to refuse an empty job
        before the device is contacted.

        Returns:
            The number of bytes sent.
        """
        job = self._raw_job(data)
        port = self._raw_port(logical_printer)
        return self._send_raw(self.read_config(), logical_printer, port, job)

    def print_raw_verified(
        self, logical_printer: int, data: PrintData | bytes, *, timeout: float = DEFAULT_VERIFY_TIMEOUT
    ) -> PortStatus:
        """Wait until the routed port is idle, send ``data``, and wait until it is idle again.

        A plain RAW send succeeds once the device took the bytes, whatever the port is doing.
        Measured on a PS301 (FW 6022): a port held by another job accepts a new one without
        complaint, the first status read after a job a printer took says ``Idle``, and after one no
        printer takes it says ``Printing`` until a restart. Idle means the port is free, never that
        a page came out.

        Args:
            logical_printer: The logical printer (1-3).
            data: The print data, sent piece by piece (plain bytes are wrapped); the bytes sent
                are counted in ``PrintData.bytes_read`` for a caller that needs a pipe's size.
            timeout: Seconds each of the two waits may take, so the worst case is twice this.

        Returns:
            The status of the routed port once it is idle after the send.

        Raises:
            ValueError: The data is empty or the printer has no RAW port; nothing was sent.
            DeviceResponseError: The printer is routed to a port the status does not list.
            PortBusyError: The port stayed busy before the send; nothing was sent.
            JobNotDrainedError: The data was sent and the port stayed busy or could not be read.
            DeviceUnavailableError: The device failed before or during the send, never after it.
        """
        job = self._raw_job(data)
        port = self._raw_port(logical_printer)
        config = self.read_config()
        routed = config.logical_printers[logical_printer - 1].port
        host = self._endpoint.host
        before = self._last_read_until_idle(logical_printer, routed, timeout=timeout)
        if isinstance(before, DeviceUnavailableError):
            raise DeviceUnavailableError(
                f"{host}: nothing was sent, {routed.value} could not be read for {timeout:g} s: {before}"
            ) from before
        if before.state is not PortState.IDLE:
            busy = self._judge(before, config)
            raise PortBusyError(
                f"{host}: nothing was sent, {_busy_reason(busy, f'after {timeout:g} s', stuck='a stuck port')}"
            )
        self._send_raw(config, logical_printer, port, job)
        # The data is sent from here on, so no failure may be a DeviceUnavailableError: a caller
        # reads that as unsent, and a resend prints the job twice. The probe a wedge check makes
        # raises one, hence its own guard.
        after = self._last_read_until_idle(logical_printer, routed, timeout=timeout)
        if isinstance(after, DeviceUnavailableError):
            raise JobNotDrainedError(
                f"{host}: the data was sent, but {routed.value} could not be read {timeout:g} s later: {after}"
            ) from after
        if after.state is not PortState.IDLE:
            try:
                busy = self._judge(after, config)
            except DeviceUnavailableError:
                busy = PortHealth(status=after, verdict=PortVerdict.PRINTING)
            raise JobNotDrainedError(
                f"{host}: the data was sent, but {_busy_reason(busy, f'{timeout:g} s later', stuck='the port')}"
            )
        return after

    # ------------------------------------------------------------------ helpers

    def _send_raw(self, config: DeviceConfig, logical_printer: int, port: int, job: PrintData) -> int:
        routed = config.logical_printers[logical_printer - 1].port
        return self._ports.raw.send(self._endpoint, port, job, drain=link_drain_for(config, routed))

    def _health(self, statuses: tuple[PortStatus, ...]) -> tuple[PortHealth, ...]:
        """Judge every port; the configuration is read only when a port needs probing."""
        if not any(is_wedge_candidate(status) for status in statuses):
            return tuple(PortHealth(status=status, verdict=unprobed_verdict(status)) for status in statuses)
        config = self.read_config()
        return tuple(self._judge(status, config) for status in statuses)

    def _judge(self, status: PortStatus, config: DeviceConfig) -> PortHealth:
        if not is_wedge_candidate(status):
            return PortHealth(status=status, verdict=unprobed_verdict(status))
        ports = self._raw_ports_routed_to(status.port, config)
        accepted = tuple(self._ports.raw.accepts_connection(self._endpoint, port) for port in ports)
        return PortHealth(status=status, verdict=probed_verdict(accepted=accepted), probed=ports)

    def _raw_ports_routed_to(self, port: PortId, config: DeviceConfig) -> tuple[int, ...]:
        printers = config.logical_printers[:_RAW_LAST_PRINTER]
        return tuple(self._raw_port_base + printer.number - 1 for printer in printers if printer.port is port)

    @staticmethod
    def _raw_job(data: PrintData | bytes) -> PrintData:
        """Refuse an empty job; return the data to send, which for a pipe is a new object.

        Callers run this before :meth:`_raw_port`, so an empty job is refused first and before
        the device is contacted: data that no printer takes leaves the port busy. A pipe has no
        size, so its first piece is read to tell.
        """
        job = (data if isinstance(data, PrintData) else PrintData.of(data)).unless_empty()
        if job is None:
            raise ValueError("refusing to open a RAW print port without data to send")
        return job

    def _raw_port(self, logical_printer: int) -> int:
        port = self._raw_port_base + logical_printer - 1
        if logical_printer < 1 or port > _RAW_LAST_PORT:
            raise ValueError(f"logical printer {logical_printer} has no RAW port")
        if logical_printer > _RAW_LAST_PRINTER:
            raise ValueError(f"logical printer {logical_printer} has no RAW port: only L1..L3 have one")
        return port

    def _routed_status(self, logical_printer: int, routed: PortId) -> PortStatus:
        for status in self.status():
            if status.port is routed:
                return status
        raise DeviceResponseError(f"L{logical_printer} is routed to {routed.value}, which the status does not list")

    def _last_read_until_idle(
        self, logical_printer: int, routed: PortId, *, timeout: float
    ) -> PortStatus | DeviceUnavailableError:
        """Read the port until it is idle or the time is up; return the last read, or why it failed.

        One unanswered read says nothing about the port, so only the last one decides. The caller
        words the failure, since it alone knows whether the data has been sent.
        """
        deadline = self._clock() + timeout
        while True:
            latest: PortStatus | DeviceUnavailableError
            try:
                latest = self._routed_status(logical_printer, routed)
            except DeviceUnavailableError as error:
                latest = error
            if isinstance(latest, PortStatus) and latest.state is PortState.IDLE:
                return latest
            left = deadline - self._clock()
            if left <= 0:
                return latest
            self._sleep(min(_VERIFY_POLL_INTERVAL, left))

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

    def _wait_for_restart(self, triggered: float, endpoint: DeviceEndpoint) -> None:
        """Wait until the device at ``endpoint`` has booted since ``triggered`` and answers FTP.

        The proof is an uptime no longer than the time since the trigger, read at the address the
        device answers on afterwards. No uptime from before the trigger is needed, which matters:
        measured, the SNMP agent stays silent at a borrowed address (the ARP trick), and answers
        there only once the restart made that address its own. Watching FTP go down instead
        missed the restart in both measured attempts: the reboot is shorter than the FTP client's
        2 s retry of a refused connect, and the manual says reachability cannot show it.
        """
        deadline = self._clock() + _RESTART_TIMEOUT
        heard: list[float] = []

        def restarted() -> bool:
            uptime = self._uptime(endpoint)
            if uptime is None:
                return False
            heard.append(uptime)
            # At most the time since the trigger: a device that did not restart has run longer, by
            # however long it ran before. Equal counts - a coarse clock (Windows) gives equality.
            return uptime <= self._clock() - triggered

        try:
            self._wait_until(deadline, restarted, host=endpoint.host, what="restart")
        except DeviceUnavailableError as error:
            if heard:
                raise
            raise DeviceUnavailableError(
                f"{endpoint.host} gave no SNMP answer within {_RESTART_TIMEOUT:g} s, "
                "so its restart could not be confirmed"
            ) from error
        self._wait_until(deadline, lambda: self._answers_ftp(endpoint), host=endpoint.host, what="answer again")

    def _wait_until(self, deadline: float, condition: Callable[[], bool], *, host: str, what: str) -> None:
        while not condition():
            if self._clock() > deadline:
                raise DeviceUnavailableError(f"{host} did not {what} within {_RESTART_TIMEOUT:g} s")
            self._sleep(_POLL_INTERVAL)

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
        # A reset device's server name is empty, and "" must not count as repeating it.
        names = {name.upper() for name in (info.server_name, info.default_name) if name}
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
        # PSINF is readable without a login on this family; its server name is the login, and after
        # a factory reset, which empties the server name, the default name is (measured, FW 6022).
        device = parse_psinf(self._ports.ftp.retrieve(self._endpoint, ReadableFile.PSINF).decode("ascii", "replace"))
        return call(self._endpoint.model_copy(update={"login": device.server_name or device.default_name}))


def _describe_changes(changes: list[ConfigChange]) -> str:
    return "; ".join(f"{change.token}: sent {change.old!r}, stored {change.new!r}" for change in changes)


def _occupancy(status: PortStatus) -> str:
    return f"occupied by {status.occupied_by}, {status.bytes_serviced} bytes serviced"


def _busy_reason(health: PortHealth, when: str, *, stuck: str) -> str:
    """Say why a port is still busy ``when``, naming a wedge or another client where a probe found one."""
    status = health.status
    seen = f"{status.state.value} {when} ({_occupancy(status)})"
    if health.verdict is PortVerdict.WEDGED:
        return (
            f"{status.port.value} is wedged: it still reads {seen} and every RAW port routed there accepts a "
            "connection; `check --reset --yes` clears it"
        )
    if health.verdict is PortVerdict.HELD:
        return f"{status.port.value} is still {seen}; another client holds it"
    return f"{status.port.value} is still {seen}; a restart clears {stuck}"


__all__ = ["DEFAULT_VERIFY_TIMEOUT", "CheckResult", "ConfigWriteResult", "DevicePorts", "PrintServer"]
