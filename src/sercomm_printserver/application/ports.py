"""Application ports - callable Protocol definitions for adapter functions.

Each Protocol class defines a ``__call__`` method whose signature exactly
matches the corresponding adapter function.  Existing module-level functions
satisfy these protocols automatically via structural subtyping (PEP 544).

System Role:
    Sits between domain and adapters.  Infrastructure types (``Config``)
    are imported under ``TYPE_CHECKING`` only so that
    import-linter layer contracts remain satisfied at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from ipaddress import IPv4Network
    from pathlib import Path

    from lib_layered_config import Config

    from ..domain.device_files import DeviceAction, ReadableFile, WritableFile
    from ..domain.endpoint import DeviceEndpoint, PrintJob
    from ..domain.enums import DeployTarget, OutputFormat
    from .discovery import ProbeHit
    from .print_server import PrintServer


class GetConfig(Protocol):
    """Load layered configuration with application defaults."""

    def __call__(
        self, *, profile: str | None = ..., start_dir: str | None = ..., dotenv_path: str | None = ...
    ) -> Config: ...


class GetDefaultConfigPath(Protocol):
    """Return the path to the bundled default configuration file."""

    def __call__(self) -> Path: ...


class DeployConfiguration(Protocol):
    """Deploy default configuration to specified target layers."""

    def __call__(
        self,
        *,
        targets: Sequence[DeployTarget],
        force: bool = ...,
        profile: str | None = ...,
        set_permissions: bool | None = ...,
        dir_mode: int | None = ...,
        file_mode: int | None = ...,
        permission_overrides: Mapping[str, object] | None = ...,
    ) -> list[Path]: ...


class DisplayConfig(Protocol):
    """Display the provided configuration in the requested format."""

    def __call__(
        self, config: Config, *, output_format: OutputFormat = ..., section: str | None = ..., profile: str | None = ...
    ) -> None: ...


class InitLogging(Protocol):
    """Initialize lib_log_rich runtime with the provided configuration.

    ``dotenv_path`` is the ``.env`` the configuration was loaded with, or None for the one the
    configuration's provenance names.
    A refused logging setting raises ``InvalidLoggingConfigError`` only after logging has been
    started with its defaults, so the caller never has to start it a second time.
    """

    def __call__(self, config: Config, *, dotenv_path: str | None = None) -> None: ...


class CheckLoggingConfig(Protocol):
    """Refuse ``config``'s logging settings as ``InitLogging`` would, leaving the running runtime alone.

    For a configuration loaded after logging is running; a refused setting raises
    ``InvalidLoggingConfigError`` and logging keeps running with the settings it started with.
    """

    def __call__(self, config: Config) -> None: ...


class FtpPort(Protocol):
    """FTP access to the print server: firmware version, virtual files, actions.

    The device serves one connection at a time, refuses PASV (active mode only) and refuses a
    new connection for about 0.1 s after the previous one closed; an adapter opens a fresh
    connection per call and absorbs that short refusal.

    Every method raises ``DeviceUnavailableError`` when the device cannot be reached,
    ``AuthenticationRequiredError`` on a 530 reply and ``DeviceResponseError`` on any other
    unexpected reply.
    """

    def system_reply(self, endpoint: DeviceEndpoint) -> str:
        """Return the reply to ``SYST`` (``215 Print Server FW nnnn``); needs no login."""
        ...

    def retrieve(self, endpoint: DeviceEndpoint, name: ReadableFile) -> bytes:
        """Return the bytes of a readable virtual file."""
        ...

    def store(self, endpoint: DeviceEndpoint, name: WritableFile, data: bytes) -> None:
        """Upload ``data`` as a writable virtual file."""
        ...

    def trigger(self, endpoint: DeviceEndpoint, action: DeviceAction) -> None:
        """Trigger an action by ``get`` of its file; the device may drop the connection."""
        ...


class TelnetPort(Protocol):
    """The Telnet console: no login, prompt ``PS>``, commands Help, Monitor, Exit."""

    def monitor(self, endpoint: DeviceEndpoint) -> str:
        """Return the text the ``monitor`` command prints."""
        ...


class TftpPort(Protocol):
    """TFTP access: reads and actions without any login (vendor manual; works by IP alone)."""

    def retrieve(self, endpoint: DeviceEndpoint, name: ReadableFile) -> bytes:
        """Return the bytes of a readable virtual file."""
        ...

    def trigger(self, endpoint: DeviceEndpoint, action: DeviceAction) -> None:
        """Trigger an action by requesting its file."""
        ...


class LpdPort(Protocol):
    """LPD (RFC 1179) on port 515; queues are the logical printers ``L1``..``L8``."""

    def queue_state(self, endpoint: DeviceEndpoint, queue: str, *, long_format: bool) -> str:
        """Return the queue state text (command 0x03 short, 0x04 long). Prints nothing."""
        ...

    def submit(self, endpoint: DeviceEndpoint, queue: str, job: PrintJob) -> None:
        """Send one print job to ``queue``."""
        ...


class RawPort(Protocol):
    """RAW / direct-socket printing: the bytes go straight to the port, no protocol."""

    def send(self, endpoint: DeviceEndpoint, port: int, data: bytes) -> None:
        """Connect to ``port``, send ``data``, close."""
        ...


class UptimePort(Protocol):
    """SNMP ``sysUpTime``: the one signal that tells a restart from a short refusal.

    The device keeps answering FTP for about 5 s after a ``RESET`` session that ended with
    ``QUIT`` and refuses every new connection for about 0.1 s after each session, so
    reachability cannot tell whether it restarted; its uptime falls back to near zero when it
    did. Reads only, with the SNMP read community (``public`` by factory default).
    """

    def uptime(self, endpoint: DeviceEndpoint) -> float:
        """Return the device's uptime in seconds; DeviceUnavailableError when SNMP is silent."""
        ...


class OpenPrintServer(Protocol):
    """Return a :class:`~.print_server.PrintServer` for ``endpoint`` wired to real adapters."""

    def __call__(self, endpoint: DeviceEndpoint, *, raw_port_base: int = ...) -> PrintServer: ...


class HostScanner(Protocol):
    """What discovery needs from the network."""

    def local_networks(self) -> tuple[IPv4Network, ...]:
        """Return the IPv4 networks this host is attached to."""
        ...

    def probe_ftp(self, hosts: Sequence[str], *, timeout: float) -> tuple[ProbeHit, ...]:
        """Connect to port 21 of every host; return those that greeted, with the greeting.

        Hosts that refuse, time out or are absent are left out; it sends nothing but ``QUIT``.
        """
        ...

    def mac_address(self, host: str) -> str | None:
        """Return the host's MAC from this machine's neighbour cache, or None."""
        ...


__all__ = [
    "CheckLoggingConfig",
    "DeployConfiguration",
    "DisplayConfig",
    "FtpPort",
    "GetConfig",
    "GetDefaultConfigPath",
    "HostScanner",
    "InitLogging",
    "LpdPort",
    "OpenPrintServer",
    "RawPort",
    "TelnetPort",
    "TftpPort",
    "UptimePort",
]
