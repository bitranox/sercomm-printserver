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


class JobNotDrainedError(TimeoutError):
    """A job was sent, but the port it went to was not read as idle in time.

    Distinct from :class:`DeviceUnavailableError`, which a caller can read as "nothing was sent":
    here the device took the data, so sending it again can print it twice. The port stayed busy or
    could not be read any more; a restart clears a busy port.

    Example:
        >>> isinstance(JobNotDrainedError("SP still Printing 30 s after the job was sent"), TimeoutError)
        True
    """


class PortBusyError(TimeoutError):
    """The port a verified print would use stayed busy, so nothing was sent.

    Distinct from :class:`JobNotDrainedError`: here sending the job later is safe. A busy port
    does not refuse a new job, it accepts it behind the one holding it (measured on a PS301,
    FW 6022), so a verified print waits instead of adding to a port that may be stuck.

    Example:
        >>> isinstance(PortBusyError("nothing was sent: SP is still Printing after 30 s"), TimeoutError)
        True
    """


class PrintSourceChangedError(OSError):
    """The file being printed delivered more or fewer bytes than its size announced.

    LPD announces the data file's size before the data, so a file that grows or shrinks while it
    is sent cannot be delivered as announced. The send then stops, sends no more than the
    announced bytes, and closes without the end-of-file byte, so an RFC 1179 server discards the
    job. This device prints data as it arrives, so part of the job may already be on paper: do
    not resend it blindly. The fault is on this host, not the device.

    Example:
        >>> isinstance(PrintSourceChangedError("job.prn shrank: 40 of 100 bytes sent"), OSError)
        True
    """


class SpoolError(OSError):
    """Print data of unknown size could not be copied to a temporary file; nothing was sent.

    LPD needs the size before the data, so a pipe is spooled to a temporary file first. A full
    or unwritable temporary directory fails here, before the print server is contacted; the
    message names the directory, which ``TMPDIR`` chooses.

    Example:
        >>> isinstance(SpoolError("no space left in /tmp"), OSError)
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


class UnverifiedAddressError(PermissionError):
    """The ARP trick could not prove the address it would borrow is free, so it refused.

    This host could not send an ARP request - it lacked the right to (root or ``CAP_NET_RAW``
    on Linux, root on macOS) or no interface reaches the address - and its ARP cache, which
    knows only hosts already talked to, has no entry for the address.

    Example:
        >>> isinstance(UnverifiedAddressError("cannot tell whether 192.0.2.77 is free"), PermissionError)
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
    "JobNotDrainedError",
    "NeighborTableError",
    "PortBusyError",
    "PrintSourceChangedError",
    "SpoolError",
    "UnverifiedAddressError",
]
