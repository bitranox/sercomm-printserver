"""Shared CLI constants.

Centralizes configuration values used across CLI modules to ensure consistency.

Contents:
    * :data:`CLICK_CONTEXT_SETTINGS` - Shared Click settings for help display.
    * :data:`TRACEBACK_SUMMARY_LIMIT` - Character budget for truncated tracebacks.
    * :data:`TRACEBACK_VERBOSE_LIMIT` - Character budget for verbose tracebacks.
    * :class:`CommandName` - The command paths an envelope can name.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

#: Shared Click context flags so help output stays consistent across commands.
CLICK_CONTEXT_SETTINGS: Final[dict[str, list[str]]] = {"help_option_names": ["-h", "--help"]}

#: Character budget used when printing truncated tracebacks.
TRACEBACK_SUMMARY_LIMIT: Final[int] = 500

#: Character budget used when verbose tracebacks are enabled.
TRACEBACK_VERBOSE_LIMIT: Final[int] = 10_000


class CommandName(str, Enum):
    """The command paths a machine-readable answer names in its ``command`` key.

    Each value is the path as typed after the program name, so a script matches the envelope
    against the command line it ran. A test walks the click tree to keep every value a
    registered command.

    Example:
        >>> CommandName.CREDENTIAL_SET.value
        'password set'
    """

    FIRMWARE = "firmware"
    DEVICE_INFO = "device-info"
    STATUS = "status"
    QUEUE = "queue"
    RESET = "reset"
    FACTORY_DEFAULT = "factory-default"
    STORE_IP = "store-ip"
    # Named CREDENTIAL_* like the domain's DeviceAction.CREDENTIAL_RESET: a member called
    # PASSWORD_* reads to bandit (S105) as a hardcoded password, though the value is a command path.
    CREDENTIAL_SET = "password set"
    CREDENTIAL_CLEAR = "password clear"
    DEVICE_CONFIG_SHOW = "device-config show"
    DEVICE_CONFIG_GET = "device-config get"
    DEVICE_CONFIG_SET = "device-config set"
    DEVICE_CONFIG_EXPORT = "device-config export"
    DEVICE_CONFIG_IMPORT = "device-config import"
    PRINT_LPD = "print lpd"
    PRINT_RAW = "print raw"
    DISCOVER = "discover"
    ARP_REACH = "arp reach"
    ARP_ASSIGN_IP = "arp assign-ip"
    ARP_FACTORY_RESET = "arp factory-reset"


__all__ = [
    "CLICK_CONTEXT_SETTINGS",
    "TRACEBACK_SUMMARY_LIMIT",
    "TRACEBACK_VERBOSE_LIMIT",
    "CommandName",
]
