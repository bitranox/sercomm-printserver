"""Whether a port that reads busy is printing, held by a client, or wedged.

The Telnet monitor alone cannot tell these apart. A RAW connection that lost its data (it was
opened while the device was still passing the previous job on) leaves the port reading
``Printing`` / ``Direct Socket`` with 0 bytes serviced and no client - and an open connection,
your own included, reads exactly the same. A bare connect to the RAW ports routed there decides
it (measured on a PS301, FW 6022): a port a client holds refuses a second connection outright,
a wedged one accepts it. Only a port that accepted every probe counts as wedged, so a live job
is never reported as one.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

from pydantic import BaseModel

from .port_status import PortState, PortStatus

#: What ``OCCUPIED BY`` reads while a RAW (direct socket) connection holds the port.
DIRECT_SOCKET: Final = "Direct Socket"


class PortVerdict(str, Enum):
    """What a port's state means.

    ``unprobed``: the port looks wedged, but no RAW port (L1..L3) is routed to it, so nothing
    could tell a wedge from a client.
    """

    IDLE = "idle"
    PRINTING = "printing"
    HELD = "held"
    WEDGED = "wedged"
    UNPROBED = "unprobed"


class PortHealth(BaseModel, frozen=True, extra="forbid"):
    """One port's status, what it means, and the RAW ports probed to decide it."""

    status: PortStatus
    verdict: PortVerdict
    probed: tuple[int, ...] = ()


def is_wedge_candidate(status: PortStatus) -> bool:
    """Whether ``status`` reads the way a wedged port does: Printing, Direct Socket, 0 bytes.

    Example:
        >>> from sercomm_printserver.domain.port_status import parse_monitor
        >>> [port] = parse_monitor(
        ...     "(SP)STATE: Printing\\r\\nTYPE: Serial\\r\\nPRINTER STATUS: On-Line\\r\\n"
        ...     "BYTES SERVICED:          0\\r\\nOCCUPIED BY: Direct Socket\\r\\n"
        ... )
        >>> is_wedge_candidate(port)
        True
    """
    return status.state is PortState.PRINTING and status.occupied_by == DIRECT_SOCKET and status.bytes_serviced == 0


def unprobed_verdict(status: PortStatus) -> PortVerdict:
    """The verdict a port gets without probing: idle, printing, or unprobed for a candidate."""
    if status.state is PortState.IDLE:
        return PortVerdict.IDLE
    return PortVerdict.UNPROBED if is_wedge_candidate(status) else PortVerdict.PRINTING


def probed_verdict(*, accepted: tuple[bool, ...]) -> PortVerdict:
    """The verdict for a candidate from its probes: wedged only when every probe got in.

    Example:
        >>> probed_verdict(accepted=(True, True)).value, probed_verdict(accepted=(True, False)).value
        ('wedged', 'held')
    """
    if not accepted:
        return PortVerdict.UNPROBED
    return PortVerdict.WEDGED if all(accepted) else PortVerdict.HELD


__all__ = [
    "DIRECT_SOCKET",
    "PortHealth",
    "PortVerdict",
    "is_wedge_candidate",
    "probed_verdict",
    "unprobed_verdict",
]
