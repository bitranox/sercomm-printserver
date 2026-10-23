"""Composition root wiring adapters to application ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..adapters.config.deploy import deploy_configuration
from ..adapters.config.display import display_config

# Configuration services
from ..adapters.config.loader import get_config, get_default_config_path

# Device services
from ..adapters.discovery import FtpBannerScanner
from ..adapters.ftp import FtpClient
from ..adapters.logging.setup import check_logging_config, init_logging
from ..adapters.lpd import LpdClient
from ..adapters.raw import RawPrinter
from ..adapters.telnet import TelnetClient
from ..adapters.tftp import TftpClient
from ..application.print_server import DevicePorts, PrintServer

# Static conformance assertions - pyright verifies that each adapter function
# structurally satisfies its corresponding Protocol at type-check time.
if TYPE_CHECKING:
    from ..adapters.memory.device import FakeDevice
    from ..adapters.memory.discovery import FakeScanner
    from ..application.ports import (
        CheckLoggingConfig,
        DeployConfiguration,
        DisplayConfig,
        FtpPort,
        GetConfig,
        GetDefaultConfigPath,
        HostScanner,
        InitLogging,
        LpdPort,
        OpenPrintServer,
        RawPort,
        TelnetPort,
        TftpPort,
    )
    from ..domain.endpoint import DeviceEndpoint

    _assert_get_config: GetConfig = get_config
    _assert_get_default_config_path: GetDefaultConfigPath = get_default_config_path
    _assert_deploy_configuration: DeployConfiguration = deploy_configuration
    _assert_display_config: DisplayConfig = display_config
    _assert_init_logging: InitLogging = init_logging
    _assert_check_logging_config: CheckLoggingConfig = check_logging_config
    _assert_ftp: FtpPort = FtpClient()
    _assert_telnet: TelnetPort = TelnetClient()
    _assert_tftp: TftpPort = TftpClient()
    _assert_lpd: LpdPort = LpdClient()
    _assert_raw: RawPort = RawPrinter()
    _assert_scanner: HostScanner = FtpBannerScanner()


def open_print_server(endpoint: DeviceEndpoint, *, raw_port_base: int = 9100) -> PrintServer:
    """Return a :class:`PrintServer` for ``endpoint`` that talks to the real device.

    Example:
        >>> from sercomm_printserver.domain.endpoint import DeviceEndpoint
        >>> open_print_server(DeviceEndpoint(host="192.0.2.52")).endpoint.host
        '192.0.2.52'
    """
    ports = DevicePorts(ftp=FtpClient(), telnet=TelnetClient(), tftp=TftpClient(), lpd=LpdClient(), raw=RawPrinter())
    return PrintServer(endpoint, ports, raw_port_base=raw_port_base)


@dataclass(frozen=True, slots=True)
class AppServices:
    """Frozen container holding all application port implementations."""

    get_config: GetConfig
    get_default_config_path: GetDefaultConfigPath
    deploy_configuration: DeployConfiguration
    display_config: DisplayConfig
    init_logging: InitLogging
    check_logging_config: CheckLoggingConfig
    open_print_server: OpenPrintServer
    host_scanner: HostScanner


def build_production() -> AppServices:
    """Wire production adapters into an AppServices container."""
    return AppServices(
        get_config=get_config,
        get_default_config_path=get_default_config_path,
        deploy_configuration=deploy_configuration,
        display_config=display_config,
        init_logging=init_logging,
        check_logging_config=check_logging_config,
        open_print_server=open_print_server,
        host_scanner=FtpBannerScanner(),
    )


def build_testing(*, device: FakeDevice | None = None, scanner: FakeScanner | None = None) -> AppServices:
    """Wire in-memory adapters into an AppServices container.

    Args:
        device: The in-memory print server every device command talks to; a bare one when None.
        scanner: The in-memory network discovery probes; an empty one when None.

    Returns:
        AppServices container with in-memory adapters.
    """
    from ..adapters.memory import (  # noqa: PLC0415 - deferred: keeps in-memory test doubles out of the production import path
        check_logging_config_in_memory,
        deploy_configuration_in_memory,
        display_config_in_memory,
        get_config_in_memory,
        get_default_config_path_in_memory,
        init_logging_in_memory,
    )
    from ..adapters.memory.device import (  # noqa: PLC0415 - deferred: keeps in-memory test doubles out of the production import path
        FakeDevice,
        FakeTftp,
    )
    from ..adapters.memory.discovery import (  # noqa: PLC0415 - deferred: keeps in-memory test doubles out of the production import path
        FakeScanner,
    )

    fake = device if device is not None else FakeDevice(config="", psinf="", monitor="")

    def open_fake(endpoint: DeviceEndpoint, *, raw_port_base: int = 9100) -> PrintServer:
        ports = DevicePorts(ftp=fake, telnet=fake, tftp=FakeTftp(fake), lpd=fake, raw=fake)
        return PrintServer(endpoint, ports, raw_port_base=raw_port_base)

    return AppServices(
        get_config=get_config_in_memory,
        get_default_config_path=get_default_config_path_in_memory,
        deploy_configuration=deploy_configuration_in_memory,
        display_config=display_config_in_memory,
        init_logging=init_logging_in_memory,
        check_logging_config=check_logging_config_in_memory,
        open_print_server=open_fake,
        host_scanner=scanner if scanner is not None else FakeScanner(hits={}),
    )


__all__ = [
    "AppServices",
    "build_production",
    "build_testing",
    "check_logging_config",
    "deploy_configuration",
    "display_config",
    "get_config",
    "get_default_config_path",
    "init_logging",
    "open_print_server",
]
