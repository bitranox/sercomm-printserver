"""TftpClient against a loopback TFTP server: request and ACK bytes, retransmits, every error."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fake_tftp_server import FakeTftpServer, ack_packet, data_packet, error_packet

from sercomm_printserver.adapters.tftp import TftpClient
from sercomm_printserver.domain.device_files import DeviceAction, ReadableFile
from sercomm_printserver.domain.endpoint import DeviceEndpoint
from sercomm_printserver.domain.errors import DeviceResponseError, DeviceUnavailableError

if TYPE_CHECKING:
    from sercomm_printserver.application.ports import TftpPort

#: Protocol timing: how long the client waits before retransmitting, not a sleep in the test.
_TIMEOUT = 0.2

_CONFIG_RRQ = b"\x00\x01CONFIG\x00octet\x00"


def _endpoint(port: int) -> DeviceEndpoint:
    return DeviceEndpoint(host="127.0.0.1", tftp_port=port, timeout=_TIMEOUT)


def _acks(count: int) -> list[bytes]:
    return [ack_packet(number) for number in range(1, count + 1)]


def test_the_client_satisfies_the_port() -> None:
    port: TftpPort = TftpClient()

    assert isinstance(port, TftpClient)


def test_retrieve_sends_an_octet_read_request_and_acks_each_block() -> None:
    content = bytes(range(256)) * 5  # 1280 bytes: two full blocks and a short one

    with FakeTftpServer(content=content) as server:
        data = TftpClient().retrieve(_endpoint(server.port), ReadableFile.CONFIG)

    assert data == content
    assert server.requests == [_CONFIG_RRQ]
    assert server.transfer_packets == _acks(3)


def test_a_file_of_exactly_two_blocks_ends_with_an_empty_block() -> None:
    content = b"P" * 1024

    with FakeTftpServer(content=content) as server:
        data = TftpClient().retrieve(_endpoint(server.port), ReadableFile.PSINF)

    assert data == content
    assert server.requests == [b"\x00\x01PSINF\x00octet\x00"]
    assert server.transfer_packets == _acks(3)


def test_an_empty_file_is_one_empty_block() -> None:
    with FakeTftpServer(content=b"") as server:
        data = TftpClient().retrieve(_endpoint(server.port), ReadableFile.CONFIG)

    assert data == b""
    assert server.transfer_packets == _acks(1)


def test_a_lost_first_block_makes_the_client_repeat_its_request() -> None:
    with FakeTftpServer(content=b"config text", drop_block=1) as server:
        data = TftpClient().retrieve(_endpoint(server.port), ReadableFile.CONFIG)

    assert data == b"config text"
    assert server.requests == [_CONFIG_RRQ, _CONFIG_RRQ]
    assert server.transfer_packets == _acks(1)


def test_a_lost_later_block_makes_the_client_repeat_its_last_ack_to_the_transfer_port() -> None:
    content = b"Q" * 1300

    with FakeTftpServer(content=content, drop_block=2) as server:
        data = TftpClient().retrieve(_endpoint(server.port), ReadableFile.CONFIG)

    assert data == content
    assert server.transfer_packets == [ack_packet(1), ack_packet(1), ack_packet(2), ack_packet(3)]


def test_a_stranger_gets_error_5_and_the_transfer_goes_on() -> None:
    content = b"R" * 1300

    with FakeTftpServer(content=content, stray_after_block=1) as server:
        data = TftpClient().retrieve(_endpoint(server.port), ReadableFile.CONFIG)

    assert data == content
    assert server.stray_reply == error_packet(5, b"Unknown transfer ID")
    assert server.transfer_packets == _acks(3)


def test_an_error_packet_is_a_response_error_quoting_the_message() -> None:
    with (
        FakeTftpServer(raw_reply=error_packet(1, b"File not found")) as server,
        pytest.raises(DeviceResponseError, match="TFTP error 1: 'File not found'"),
    ):
        TftpClient().retrieve(_endpoint(server.port), ReadableFile.CONFIG)

    assert server.transfer_packets == []


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (b"\x00\x03", "malformed TFTP packet"),
        (ack_packet(1), "opcode 4 where DATA was expected"),
        (data_packet(1, b"W" * 513), "513-byte TFTP block"),
    ],
)
def test_a_reply_that_is_not_tftp_data_is_a_response_error(reply: bytes, message: str) -> None:
    with FakeTftpServer(raw_reply=reply) as server, pytest.raises(DeviceResponseError, match=message):
        TftpClient().retrieve(_endpoint(server.port), ReadableFile.CONFIG)

    assert server.transfer_packets == []


def test_a_silent_device_gets_three_retransmissions_then_is_unavailable() -> None:
    with FakeTftpServer(silent=True) as server, pytest.raises(DeviceUnavailableError, match=f"127.0.0.1:{server.port}"):
        TftpClient().retrieve(_endpoint(server.port), ReadableFile.CONFIG)

    assert server.requests == [_CONFIG_RRQ] * 4


def test_a_transfer_that_stops_midway_is_a_response_error_for_retrieve() -> None:
    with (
        FakeTftpServer(content=b"S" * 1300, stop_after_blocks=2) as server,
        pytest.raises(DeviceResponseError, match="after 1024 bytes"),
    ):
        TftpClient().retrieve(_endpoint(server.port), ReadableFile.CONFIG)

    assert server.transfer_packets == _acks(2)


def test_more_than_one_mib_is_refused_and_the_server_told() -> None:
    with (
        FakeTftpServer(content=b"T" * (1024 * 1024 + 1)) as server,
        pytest.raises(DeviceResponseError, match="more than 1048576 bytes"),
    ):
        TftpClient().retrieve(_endpoint(server.port), ReadableFile.CONFIG)

    assert server.transfer_packets[:-1] == _acks(2048)
    assert server.transfer_packets[-1] == error_packet(3, b"File too large")


def test_trigger_requests_the_action_file_and_consumes_the_data() -> None:
    with FakeTftpServer(content=b"U" * 600) as server:
        TftpClient().trigger(_endpoint(server.port), DeviceAction.RESET)

    assert server.requests == [b"\x00\x01RESET\x00octet\x00"]
    assert server.transfer_packets == _acks(2)


def test_trigger_counts_a_transfer_cut_off_by_the_device_as_done() -> None:
    with FakeTftpServer(content=b"V" * 1300, stop_after_blocks=1) as server:
        TftpClient().trigger(_endpoint(server.port), DeviceAction.FACTORY_DEFAULT)

    assert server.requests == [b"\x00\x01DEFAULTC\x00octet\x00"]
    assert server.transfer_packets == _acks(1)


def test_trigger_on_a_silent_device_is_unavailable() -> None:
    with FakeTftpServer(silent=True) as server, pytest.raises(DeviceUnavailableError, match="after 3 retransmissions"):
        TftpClient().trigger(_endpoint(server.port), DeviceAction.RESET)

    assert server.requests == [b"\x00\x01RESET\x00octet\x00"] * 4


def test_trigger_reports_an_error_packet() -> None:
    with (
        FakeTftpServer(raw_reply=error_packet(2, b"Access violation")) as server,
        pytest.raises(DeviceResponseError, match="TFTP error 2: 'Access violation'"),
    ):
        TftpClient().trigger(_endpoint(server.port), DeviceAction.CREDENTIAL_RESET)

    assert server.requests == [b"\x00\x01PASSRESET\x00octet\x00"]
