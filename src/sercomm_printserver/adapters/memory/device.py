"""An in-memory print server that implements every protocol port.

One :class:`FakeDevice` stands behind all five ports at once, so a test (or a dry run) can drive
:class:`~sercomm_printserver.application.print_server.PrintServer` end to end without a network.
It behaves as the measured PS301 does where that matters to a caller: ``CONFIG`` and ``PSINF``
read without a login, a stored ``CONFIG`` replaces the file verbatim, and ``MAIL_PAS`` reads back
masked. Writes can be made to require the device-name login, as the vendor manuals describe.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from ...domain.device_files import DeviceAction, ReadableFile, WritableFile
from ...domain.errors import AuthenticationRequiredError, DeviceUnavailableError

if TYPE_CHECKING:
    from ...domain.endpoint import DeviceEndpoint, PrintJob

_MASKED_MAIL_PASSWORD: Final = re.compile(r"^(4102 MAIL_PAS:).*$", re.MULTILINE)


class FakeDevice:
    """A print server held in memory.

    Args:
        config: The CONFIG file the device starts with.
        psinf: The PSINF report.
        monitor: What the Telnet ``monitor`` command prints.
        firmware: The firmware version ``SYST`` reports.
        login_for_writes: When set, ``store`` and ``trigger`` answer 530 unless the endpoint logs
            in with this name and the device's password.

    Example:
        >>> from sercomm_printserver.domain.endpoint import DeviceEndpoint
        >>> device = FakeDevice(config="0001 BOX_NAME:X\\n", psinf="", monitor="")
        >>> device.retrieve(DeviceEndpoint(host="192.0.2.1"), ReadableFile.CONFIG)
        b'0001 BOX_NAME:X\\n'
    """

    def __init__(
        self,
        *,
        config: str,
        psinf: str,
        monitor: str,
        firmware: str = "6022",
        login_for_writes: str | None = None,
    ) -> None:
        self.config = config
        self.psinf = psinf
        self.monitor_text = monitor
        self.firmware = firmware
        self.login_for_writes = login_for_writes
        self.credential = ""
        self.reachable = True
        self.actions: list[DeviceAction] = []
        self.lpd_jobs: list[tuple[str, PrintJob]] = []
        self.raw_sends: list[tuple[int, bytes]] = []
        self.store_rewrites: dict[str, str] = {}

    # FtpPort --------------------------------------------------------------

    def system_reply(self, endpoint: DeviceEndpoint) -> str:
        """Answer ``SYST``."""
        self._check_reachable(endpoint)
        return f"215 Print Server FW {self.firmware}"

    def retrieve(self, endpoint: DeviceEndpoint, name: ReadableFile) -> bytes:
        """Return CONFIG (mail password masked, as the device does) or PSINF."""
        self._check_reachable(endpoint)
        if name is ReadableFile.CONFIG:
            return _MASKED_MAIL_PASSWORD.sub(r"\g<1>**********", self.config).encode("ascii")
        return self.psinf.encode("ascii")

    def store(self, endpoint: DeviceEndpoint, name: WritableFile, data: bytes) -> None:
        """Replace CONFIG or set the password; ``store_rewrites`` can make it store other text."""
        self._check_writable(endpoint)
        text = data.decode("ascii")
        if name is WritableFile.CONFIG:
            self.config = self.store_rewrites.get(text, text)
        else:
            self.credential = text

    def trigger(self, endpoint: DeviceEndpoint, action: DeviceAction) -> None:
        """Record the action after the login check FTP applies to it."""
        self._check_writable(endpoint)
        self.record_action(endpoint, action)

    def record_action(self, endpoint: DeviceEndpoint, action: DeviceAction) -> None:
        """Record an action with no login check; clearing the password takes effect at once."""
        self._check_reachable(endpoint)
        self.actions.append(action)
        if action is DeviceAction.CREDENTIAL_RESET:
            self.credential = ""

    # TelnetPort -----------------------------------------------------------

    def monitor(self, endpoint: DeviceEndpoint) -> str:
        """Return the monitor text."""
        self._check_reachable(endpoint)
        return self.monitor_text

    # LpdPort ---------------------------------------------------------------

    def queue_state(self, endpoint: DeviceEndpoint, queue: str, *, long_format: bool) -> str:
        """Report the number of jobs received for ``queue``."""
        self._check_reachable(endpoint)
        jobs = sum(1 for name, _ in self.lpd_jobs if name == queue)
        return f"{queue}: {jobs} job(s){' (long)' if long_format else ''}\n"

    def submit(self, endpoint: DeviceEndpoint, queue: str, job: PrintJob) -> None:
        """Record the job."""
        self._check_reachable(endpoint)
        self.lpd_jobs.append((queue, job))

    # RawPort ---------------------------------------------------------------

    def send(self, endpoint: DeviceEndpoint, port: int, data: bytes) -> None:
        """Record the bytes sent to ``port``."""
        self._check_reachable(endpoint)
        self.raw_sends.append((port, data))

    # ------------------------------------------------------------------------

    def _check_reachable(self, endpoint: DeviceEndpoint) -> None:
        if not self.reachable:
            raise DeviceUnavailableError(f"{endpoint.host} does not answer")

    def _check_writable(self, endpoint: DeviceEndpoint) -> None:
        self._check_reachable(endpoint)
        if self.login_for_writes is None:
            return
        logged_in = endpoint.login == self.login_for_writes
        if not logged_in or endpoint.password.get_secret_value() != self.credential:
            raise AuthenticationRequiredError("530 Not logged in.")


class FakeTftp:
    """TFTP side of a :class:`FakeDevice`: reads its files and records its actions without login."""

    def __init__(self, device: FakeDevice) -> None:
        self._device = device

    def retrieve(self, endpoint: DeviceEndpoint, name: ReadableFile) -> bytes:
        """Read a file of the device."""
        return self._device.retrieve(endpoint, name)

    def trigger(self, endpoint: DeviceEndpoint, action: DeviceAction) -> None:
        """Record the action; TFTP has no login."""
        self._device.record_action(endpoint, action)


__all__ = ["FakeDevice", "FakeTftp"]
