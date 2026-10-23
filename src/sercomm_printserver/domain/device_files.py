"""The print server's virtual FTP/TFTP files, split by what touching them does.

On this firmware family a ``get`` of ``RESET``, ``DEFAULTC``, ``PASSRESET`` or ``SETIP`` reads
nothing: it triggers the action. Keeping readable files and actions in separate enums means a
caller cannot reset a device by asking to read a file - the type does not allow the name.
"""

from __future__ import annotations

from enum import Enum


class ReadableFile(str, Enum):
    """Files a ``get`` really reads.

    Example:
        >>> ReadableFile.CONFIG.value
        'CONFIG'
    """

    CONFIG = "CONFIG"
    PSINF = "PSINF"


class WritableFile(str, Enum):
    """Files a ``put`` writes.

    Attributes:
        CONFIG: The configuration; it takes effect after a reset.
        LOGIN_CREDENTIAL: The file ``PASSWORD``: a new login password, at most 19 bytes.
    """

    CONFIG = "CONFIG"
    LOGIN_CREDENTIAL = "PASSWORD"


class DeviceAction(str, Enum):
    """Files whose ``get`` triggers an action instead of reading.

    Attributes:
        RESET: Restart; a stored CONFIG takes effect.
        FACTORY_DEFAULT: Restore factory settings; the IP becomes 0.0.0.0.
        CREDENTIAL_RESET: The file ``PASSRESET``: clear the login password.
        STORE_IP: Save the address the device currently answers on as its static IP.
    """

    RESET = "RESET"
    FACTORY_DEFAULT = "DEFAULTC"
    CREDENTIAL_RESET = "PASSRESET"
    STORE_IP = "SETIP"


__all__ = ["DeviceAction", "ReadableFile", "WritableFile"]
