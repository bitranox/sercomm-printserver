"""CLI command implementations.

Collects all subcommand functions and re-exports them for registration
with the root CLI group.

Contents:
    * Info commands from :mod:`.info`
    * App configuration commands from :mod:`.config`
    * Device commands from :mod:`.device`, :mod:`.device_config` and :mod:`.printing`
"""

from __future__ import annotations

from .config import cli_config, cli_config_deploy, cli_config_generate_examples
from .device import (
    cli_device_info,
    cli_factory_default,
    cli_firmware,
    cli_password,
    cli_queue,
    cli_reset,
    cli_status,
    cli_store_ip,
)
from .device_config import cli_device_config
from .discover import cli_discover
from .info import cli_info
from .printing import cli_print

__all__ = [
    "cli_config",
    "cli_config_deploy",
    "cli_config_generate_examples",
    "cli_device_config",
    "cli_device_info",
    "cli_discover",
    "cli_factory_default",
    "cli_firmware",
    "cli_info",
    "cli_password",
    "cli_print",
    "cli_queue",
    "cli_reset",
    "cli_status",
    "cli_store_ip",
]
