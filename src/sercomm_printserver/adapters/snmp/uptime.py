"""Read ``sysUpTime`` with one SNMPv1 GET - the only SNMP this package needs.

A full SNMP library would be a dependency for a single read-only value, so the request is
built and the reply parsed here in BER (ITU-T X.690). The reply is parsed by structure, never by
searching for a tag byte, so a community string or request id that happens to contain the
TimeTicks tag cannot be mistaken for the value.
"""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING, Final

from ...domain.errors import DeviceResponseError, DeviceUnavailableError

if TYPE_CHECKING:
    from ...domain.endpoint import DeviceEndpoint

#: 1.3.6.1.2.1.1.3.0 (sysUpTime.0), BER-encoded.
_SYS_UPTIME: Final = bytes([0x2B, 6, 1, 2, 1, 1, 3, 0])
_SEQUENCE: Final = 0x30
_INTEGER: Final = 0x02
_OCTETS: Final = 0x04
_NULL: Final = 0x05
_OID: Final = 0x06
_GET_REQUEST: Final = 0xA0
_GET_RESPONSE: Final = 0xA2
_TIMETICKS: Final = 0x43
_TICKS_PER_SECOND: Final = 100.0
_MAX_REPLY: Final = 1500
#: BER: a length at or above this is written in long form, its low bits counting length octets.
_LONG_FORM: Final = 0x80


class SnmpUptime:
    """Implements :class:`~sercomm_printserver.application.ports.UptimePort`.

    Args:
        community: SNMP read community; the factory default is ``public``.
        port: UDP port, 161 on a real device.
    """

    def __init__(self, *, community: str = "public", port: int = 161) -> None:
        self._community = community.encode("ascii")
        self._port = port

    def uptime(self, endpoint: DeviceEndpoint) -> float:
        """Return the device's uptime in seconds."""
        request_id = int.from_bytes(os.urandom(3), "big")
        address = f"{endpoint.host}:{self._port}"
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(endpoint.timeout)
            try:
                sock.sendto(_request(self._community, request_id), (endpoint.host, self._port))
                reply, _ = sock.recvfrom(_MAX_REPLY)
            except OSError as exc:
                raise DeviceUnavailableError(f"{address} gave no SNMP answer: {exc}") from exc
        return _ticks(reply, request_id, address) / _TICKS_PER_SECOND


def _tlv(tag: int, body: bytes) -> bytes:
    length = len(body)
    header = bytes([length]) if length < _LONG_FORM else bytes([_LONG_FORM | 1, length])
    return bytes([tag]) + header + body


def _integer(value: int) -> bytes:
    return _tlv(_INTEGER, value.to_bytes(max(1, (value.bit_length() + 8) // 8), "big", signed=True))


def _request(community: bytes, request_id: int) -> bytes:
    varbind = _tlv(_SEQUENCE, _tlv(_OID, _SYS_UPTIME) + _tlv(_NULL, b""))
    pdu = _tlv(_GET_REQUEST, _integer(request_id) + _integer(0) + _integer(0) + _tlv(_SEQUENCE, varbind))
    return _tlv(_SEQUENCE, _integer(0) + _tlv(_OCTETS, community) + pdu)


class _Reader:
    """Walks BER elements in order and refuses anything malformed."""

    def __init__(self, data: bytes, address: str) -> None:
        self._data = data
        self._pos = 0
        self._address = address

    def element(self, expected: int) -> bytes:
        if self._pos + 2 > len(self._data) or self._data[self._pos] != expected:
            raise self._bad(f"expected tag 0x{expected:02x}")
        length, start = self._data[self._pos + 1], self._pos + 2
        if length & _LONG_FORM:
            octets = length & ~_LONG_FORM
            length, start = int.from_bytes(self._data[start : start + octets], "big"), start + octets
        if start + length > len(self._data):
            raise self._bad("element runs past the end")
        self._pos = start + length
        return self._data[start : start + length]

    def _bad(self, reason: str) -> DeviceResponseError:
        return DeviceResponseError(f"{self._address} sent a malformed SNMP reply: {reason}")


def _ticks(reply: bytes, request_id: int, address: str) -> int:
    message = _Reader(_Reader(reply, address).element(_SEQUENCE), address)
    message.element(_INTEGER)
    message.element(_OCTETS)
    pdu = _Reader(message.element(_GET_RESPONSE), address)
    if int.from_bytes(pdu.element(_INTEGER), "big", signed=True) != request_id:
        raise DeviceResponseError(f"{address} answered another SNMP request")
    error_status = int.from_bytes(pdu.element(_INTEGER), "big")
    pdu.element(_INTEGER)
    if error_status != 0:
        raise DeviceResponseError(f"{address} refused the SNMP read (error status {error_status})")
    varbind = _Reader(_Reader(pdu.element(_SEQUENCE), address).element(_SEQUENCE), address)
    varbind.element(_OID)
    return int.from_bytes(varbind.element(_TIMETICKS), "big")


__all__ = ["SnmpUptime"]
