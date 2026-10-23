"""SnmpUptime against a loopback UDP responder that builds its replies independently."""

from __future__ import annotations

import socket
import threading
from typing import TYPE_CHECKING

import pytest

from sercomm_printserver.adapters.snmp import SnmpUptime
from sercomm_printserver.domain.endpoint import DeviceEndpoint
from sercomm_printserver.domain.errors import DeviceResponseError, DeviceUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sercomm_printserver.application.ports import UptimePort

#: sysUpTime.0 as it appears in a request and a reply.
_OID = bytes([0x06, 0x08, 0x2B, 6, 1, 2, 1, 1, 3, 0])


def _tlv(tag: int, body: bytes) -> bytes:
    assert len(body) < 128
    return bytes([tag, len(body)]) + body


def _request_id(request: bytes) -> bytes:
    """The raw INTEGER element of the request id, read from the fixed request layout."""
    community_length = request[6]
    pdu_start = 7 + community_length
    return request[pdu_start + 2 : pdu_start + 4 + request[pdu_start + 3]]


def _reply(request_id: bytes, *, ticks: int, error_status: int = 0, community: bytes = b"public") -> bytes:
    varbind = _tlv(0x30, _OID + _tlv(0x43, ticks.to_bytes(4, "big")))
    pdu = _tlv(0xA2, request_id + _tlv(0x02, bytes([error_status])) + _tlv(0x02, b"\x00") + _tlv(0x30, varbind))
    return _tlv(0x30, _tlv(0x02, b"\x00") + _tlv(0x04, community) + pdu)


class _Responder:
    """Answers each datagram with ``answer(request)``; None means stay silent."""

    def __init__(self, answer: Callable[[bytes], bytes | None]) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port: int = self.sock.getsockname()[1]
        self.requests: list[bytes] = []
        self._answer = answer
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                request, client = self.sock.recvfrom(1500)
            except OSError:
                return
            self.requests.append(request)
            reply = self._answer(request)
            if reply is not None:
                self.sock.sendto(reply, client)

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def responder_factory() -> Iterator[Callable[[Callable[[bytes], bytes | None]], _Responder]]:
    made: list[_Responder] = []

    def make(answer: Callable[[bytes], bytes | None]) -> _Responder:
        responder = _Responder(answer)
        made.append(responder)
        return responder

    yield make
    for responder in made:
        responder.close()


_ENDPOINT = DeviceEndpoint(host="127.0.0.1", timeout=0.5)


def test_the_adapter_satisfies_the_port() -> None:
    port: UptimePort = SnmpUptime()
    assert port is not None


def test_uptime_is_read_from_the_timeticks_in_seconds(
    responder_factory: Callable[[Callable[[bytes], bytes | None]], _Responder],
) -> None:
    responder = responder_factory(lambda request: _reply(_request_id(request), ticks=4470))

    assert SnmpUptime(port=responder.port).uptime(_ENDPOINT) == 44.7
    request = responder.requests[0]
    assert b"\x04\x06public" in request
    assert _OID + b"\x05\x00" in request


def test_the_community_is_configurable(
    responder_factory: Callable[[Callable[[bytes], bytes | None]], _Responder],
) -> None:
    responder = responder_factory(lambda request: _reply(_request_id(request), ticks=1))

    SnmpUptime(community="secret", port=responder.port).uptime(_ENDPOINT)

    assert b"\x04\x06secret" in responder.requests[0]


def test_a_silent_device_is_unavailable(
    responder_factory: Callable[[Callable[[bytes], bytes | None]], _Responder],
) -> None:
    responder = responder_factory(lambda _request: None)

    with pytest.raises(DeviceUnavailableError, match="gave no SNMP answer"):
        SnmpUptime(port=responder.port).uptime(_ENDPOINT)


def _error_status(request: bytes) -> bytes:
    return _reply(_request_id(request), ticks=1, error_status=2)


def _other_request(_request: bytes) -> bytes:
    return _reply(_tlv(0x02, b"\x07\x07"), ticks=1)


def _truncated(_request: bytes) -> bytes:
    return b"\x30\x05\x02\x01"


def _not_a_sequence(_request: bytes) -> bytes:
    return b"\x04\x00"


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (_error_status, "error status 2"),
        (_other_request, "another SNMP request"),
        (_truncated, "malformed SNMP reply"),
        (_not_a_sequence, "malformed SNMP reply"),
    ],
    ids=["error-status", "wrong-request-id", "truncated", "not-a-sequence"],
)
def test_a_reply_that_is_not_the_answer_is_refused(
    responder_factory: Callable[[Callable[[bytes], bytes | None]], _Responder],
    answer: Callable[[bytes], bytes | None],
    message: str,
) -> None:
    responder = responder_factory(answer)

    with pytest.raises(DeviceResponseError, match=message):
        SnmpUptime(port=responder.port).uptime(_ENDPOINT)


def test_a_community_containing_the_timeticks_tag_is_not_mistaken_for_the_value(
    responder_factory: Callable[[Callable[[bytes], bytes | None]], _Responder],
) -> None:
    community = "C" + chr(0x43) + chr(0x04)
    responder = responder_factory(
        lambda request: _reply(_request_id(request), ticks=250, community=community.encode("ascii"))
    )

    assert SnmpUptime(community=community, port=responder.port).uptime(_ENDPOINT) == 2.5
