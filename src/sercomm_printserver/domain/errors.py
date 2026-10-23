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


__all__ = [
    "ConfigFormatError",
    "ConfigurationError",
    "DeviceResponseError",
]
