"""Domain-specific exceptions for typed error handling at boundaries."""

from __future__ import annotations


class ConfigurationError(Exception):
    """Missing, invalid, or incomplete configuration.

    Raised when required configuration values are absent, malformed, or
    logically inconsistent. Typically caught at CLI boundaries to provide
    user-friendly error messages.

    Example:
        >>> from sercomm_printserver.domain.errors import ConfigurationError
        >>> err = ConfigurationError("No device host configured")
        >>> str(err)
        'No device host configured'
    """


class ConfigFormatError(ValueError):
    """A CONFIG file or one of its values is not what the print-server family uses.

    Raised while parsing a device's CONFIG text and when a changed value is refused. The
    message names the parameter by line number and token.

    Example:
        >>> str(ConfigFormatError("parameter 4000 (IP_ADDR) is 'x', expected an IPv4 address"))
        "parameter 4000 (IP_ADDR) is 'x', expected an IPv4 address"
    """


class DeviceResponseError(ValueError):
    """The print server answered, but not in the form this family of firmware uses.

    Raised by the parsers of ``PSINF``, the Telnet ``monitor`` output and protocol replies. A
    device that does not answer at all is a connection error, not this.

    Example:
        >>> str(DeviceResponseError("unexpected SYST reply '500 Invalid command'"))
        "unexpected SYST reply '500 Invalid command'"
    """


class DeviceUnavailableError(ConnectionError):
    """The print server could not be reached: refused, timed out, or no route.

    Example:
        >>> isinstance(DeviceUnavailableError("192.0.2.52:21 refused the connection"), OSError)
        True
    """


class AuthenticationRequiredError(PermissionError):
    """The print server refused the operation until the right login and password are given.

    Example:
        >>> str(AuthenticationRequiredError("530 Not logged in."))
        '530 Not logged in.'
    """


class ConfirmationRequiredError(PermissionError):
    """A destructive action was asked for without the confirmation it needs.

    Example:
        >>> str(ConfirmationRequiredError("factory default needs the device name PS_EXAMPLE"))
        'factory default needs the device name PS_EXAMPLE'
    """


class HostPrivilegeError(PermissionError):
    """This host refused to change its own network state, such as a static ARP entry.

    Raised by the ARP trick: writing the neighbour table needs root or ``CAP_NET_ADMIN`` on
    Linux, root on macOS and Administrator on Windows. The message names the remedy.

    Example:
        >>> isinstance(HostPrivilegeError("needs root or CAP_NET_ADMIN"), PermissionError)
        True
    """


class NeighborTableError(OSError):
    """This host could not write or remove a static ARP entry for a reason other than privilege.

    Example:
        >>> str(NeighborTableError("the kernel refused to add the neighbour entry"))
        'the kernel refused to add the neighbour entry'
    """


__all__ = [
    "AuthenticationRequiredError",
    "ConfigFormatError",
    "ConfigurationError",
    "ConfirmationRequiredError",
    "DeviceResponseError",
    "DeviceUnavailableError",
    "HostPrivilegeError",
    "NeighborTableError",
]
