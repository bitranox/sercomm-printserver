"""Read ``sysUpTime`` through ipscout's SNMP system read - the only SNMP this package needs.

ipscout asks the whole system group in one SNMPv1 GET and parses the reply by structure, so a
community string or request id that contains the TimeTicks tag is never mistaken for the
value. Every outcome comes back as a state rather than an exception; this adapter turns the
states into the domain errors callers above the adapter layer already handle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ipscout

from ...domain.errors import DeviceResponseError, DeviceUnavailableError

if TYPE_CHECKING:
    from ...domain.endpoint import DeviceEndpoint

#: No usable SNMP agent at the address: nothing came back, the port was closed, or the host
#: could not be reached. A device that is restarting reads this way, so it is "unavailable".
_UNAVAILABLE = frozenset({ipscout.SnmpState.SILENT, ipscout.SnmpState.REFUSED, ipscout.SnmpState.UNREACHABLE})


class SnmpUptime:
    """Implements :class:`~sercomm_printserver.application.ports.UptimePort`.

    Args:
        community: SNMP read community; the factory default is ``public``.
        port: UDP port, 161 on a real device.
    """

    def __init__(self, *, community: str = "public", port: int = 161) -> None:
        self._community = community
        self._port = port

    def uptime(self, endpoint: DeviceEndpoint) -> float:
        """Return the device's uptime in seconds.

        Raises:
            DeviceUnavailableError: No SNMP answer: silent, port closed, or no route.
            DeviceResponseError: The agent answered, but with an error or without sysUpTime.
        """
        host = endpoint.host
        replies = ipscout.read_snmp_system([host], community=self._community, port=self._port, timeout=endpoint.timeout)
        reply = replies[host]
        address = f"{host}:{self._port}"
        if reply.state in _UNAVAILABLE:
            reason = f" ({reply.error})" if reply.error else ""
            raise DeviceUnavailableError(f"{address} gave no SNMP answer: {reply.state.value}{reason}")
        if reply.state is ipscout.SnmpState.ERROR:
            raise DeviceResponseError(f"{address} sent an unusable SNMP reply: {reply.error}")
        if reply.uptime_seconds is None:
            raise DeviceResponseError(f"{address} answered SNMP without sysUpTime")
        return reply.uptime_seconds


__all__ = ["SnmpUptime"]
