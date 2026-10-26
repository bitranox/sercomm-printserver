"""SnmpUptime through the real ipscout SNMP read, against a loopback UDP agent.

The agent answers with ipscout's own BER codec: parsing BER is ipscout's job and tested there.
What is tested here is the adapter's part - which read it asks for, and how each outcome
becomes an uptime or a domain error.
"""

from __future__ import annotations

import socket
import threading
from typing import TYPE_CHECKING

import pytest
from ipscout import snmpber

from sercomm_printserver.adapters.snmp import SnmpUptime
from sercomm_printserver.domain.endpoint import DeviceEndpoint
from sercomm_printserver.domain.errors import DeviceResponseError, DeviceUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from typing import TypeAlias

    from sercomm_printserver.application.ports import UptimePort

    #: What the agent sends back for one parsed request; None stays silent.
    _Answer: TypeAlias = Callable[[snmpber.SnmpMessage], bytes | None]
    _MakeAgent: TypeAlias = Callable[[_Answer], "_Agent"]

_UPTIME_OID = "1.3.6.1.2.1.1.3.0"
#: SNMPv1 error status for an OID the agent does not know (RFC 1157).
_NO_SUCH_NAME = 2
_GEN_ERR = 5


def _reply(
    request: snmpber.SnmpMessage,
    *,
    error_status: int = 0,
    error_index: int = 0,
    bindings: tuple[snmpber.VarBind, ...] = (),
) -> bytes:
    return snmpber.encode_message(
        request.model_copy(
            update={
                "pdu_tag": snmpber.GET_RESPONSE,
                "error_status": error_status,
                "error_index": error_index,
                "bindings": bindings,
            }
        )
    )


def _uptime_only(ticks: int) -> Callable[[snmpber.SnmpMessage], bytes]:
    """An agent that knows sysUpTime alone, as SNMPv1 says so: noSuchName for any other OID."""

    def answer(request: snmpber.SnmpMessage) -> bytes:
        oids = [binding.oid for binding in request.bindings]
        unknown = [index for index, oid in enumerate(oids, start=1) if oid != _UPTIME_OID]
        if unknown:
            return _reply(request, error_status=_NO_SUCH_NAME, error_index=unknown[0], bindings=request.bindings)
        value = snmpber.VarBind(oid=_UPTIME_OID, tag=snmpber.TIMETICKS, value=ticks.to_bytes(4, "big"))
        return _reply(request, bindings=(value,))

    return answer


class _Agent:
    """Answers each request with ``answer(parsed request)``; None means stay silent."""

    def __init__(self, answer: _Answer) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port: int = self.sock.getsockname()[1]
        self.requests: list[snmpber.SnmpMessage] = []
        self._answer = answer
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                data, client = self.sock.recvfrom(1500)
            except OSError:
                return
            request = snmpber.parse_message(data)
            self.requests.append(request)
            reply = self._answer(request)
            if reply is not None:
                self.sock.sendto(reply, client)

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def agent_factory() -> Iterator[_MakeAgent]:
    made: list[_Agent] = []

    def make(answer: _Answer) -> _Agent:
        agent = _Agent(answer)
        made.append(agent)
        return agent

    yield make
    for agent in made:
        agent.close()


_ENDPOINT = DeviceEndpoint(host="127.0.0.1", timeout=0.5)


def test_the_adapter_satisfies_the_port() -> None:
    port: UptimePort = SnmpUptime()
    assert port is not None


def test_uptime_is_read_from_the_timeticks_in_seconds(agent_factory: _MakeAgent) -> None:
    agent = agent_factory(_uptime_only(4470))

    assert SnmpUptime(port=agent.port).uptime(_ENDPOINT) == 44.7
    assert agent.requests[0].version == 0, "SNMPv1, the version the PS301 agent speaks"
    assert agent.requests[0].community == b"public"
    assert _UPTIME_OID in [binding.oid for binding in agent.requests[0].bindings]


def test_the_community_is_configurable(agent_factory: _MakeAgent) -> None:
    agent = agent_factory(_uptime_only(1))

    SnmpUptime(community="secret", port=agent.port).uptime(_ENDPOINT)

    assert {request.community for request in agent.requests} == {b"secret"}


def test_a_silent_device_is_unavailable(agent_factory: _MakeAgent) -> None:
    agent = agent_factory(lambda _request: None)

    with pytest.raises(DeviceUnavailableError, match=r"127\.0\.0\.1:\d+ gave no SNMP answer: silent"):
        SnmpUptime(port=agent.port).uptime(_ENDPOINT)


def test_a_closed_snmp_port_is_unavailable() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    with pytest.raises(DeviceUnavailableError, match="gave no SNMP answer"):
        SnmpUptime(port=closed_port).uptime(_ENDPOINT)


def test_an_unresolvable_host_is_unavailable() -> None:
    with pytest.raises(DeviceUnavailableError, match="gave no SNMP answer: unreachable"):
        SnmpUptime().uptime(DeviceEndpoint(host="printer.invalid", timeout=0.5))


def test_an_agent_error_is_a_response_error(agent_factory: _MakeAgent) -> None:
    agent = agent_factory(
        lambda request: _reply(request, error_status=_GEN_ERR, error_index=1, bindings=request.bindings)
    )

    with pytest.raises(DeviceResponseError, match=r"unusable SNMP reply: .*genErr"):
        SnmpUptime(port=agent.port).uptime(_ENDPOINT)


def test_an_agent_without_sysuptime_is_a_response_error(agent_factory: _MakeAgent) -> None:
    # noSuchName for the first OID of every request: ipscout drops one per re-ask until none is left.
    agent = agent_factory(
        lambda request: _reply(request, error_status=_NO_SUCH_NAME, error_index=1, bindings=request.bindings)
    )

    with pytest.raises(DeviceResponseError, match="without sysUpTime"):
        SnmpUptime(port=agent.port).uptime(_ENDPOINT)


def test_a_community_never_appears_in_an_error(agent_factory: _MakeAgent) -> None:
    agent = agent_factory(lambda _request: b"\x30\x05\x02\x01")

    with pytest.raises((DeviceResponseError, DeviceUnavailableError)) as caught:
        SnmpUptime(community="s3cr3t-community", port=agent.port).uptime(_ENDPOINT)

    assert "s3cr3t-community" not in str(caught.value)
