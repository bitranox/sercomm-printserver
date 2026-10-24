"""Discovery: the use case over an in-memory network, the real scanner over loopback servers."""

from __future__ import annotations

import json
import socket
import threading
from ipaddress import IPv4Address, IPv4Network
from typing import TYPE_CHECKING

import pytest

from sercomm_printserver.adapters.cli import root as cli_root
from sercomm_printserver.adapters.discovery import FtpBannerScanner
from sercomm_printserver.adapters.memory.discovery import FakeScanner
from sercomm_printserver.application.discovery import MAX_HOSTS, discover
from sercomm_printserver.composition import build_testing

if TYPE_CHECKING:
    from collections.abc import Iterator

    from click.testing import CliRunner

    from sercomm_printserver.application.ports import HostScanner

_NET = IPv4Network("192.0.2.0/29")


def test_the_fake_scanner_satisfies_the_port() -> None:
    scanner: HostScanner = FakeScanner(hits=())
    assert scanner.local_networks()


# ---------------------------------------------------------------- use case


def test_print_servers_are_found_with_their_mac_and_other_ftp_servers_are_not() -> None:
    scanner = FakeScanner(
        hits=("192.0.2.3", "192.0.2.2"),
        others={"192.0.2.4": "220 ProFTPD Server ready."},
        macs={"192.0.2.3": "00:c0:02:12:34:56"},
    )

    report = discover(scanner, networks=[_NET], timeout=1.0)

    assert [(str(d.host), d.mac_address) for d in report.devices] == [
        ("192.0.2.2", None),
        ("192.0.2.3", "00:c0:02:12:34:56"),
    ]
    assert report.probed == 6
    assert scanner.probed == [str(host) for host in _NET.hosts()]


def test_without_networks_the_local_ones_are_searched_and_oversized_ones_skipped() -> None:
    scanner = FakeScanner(hits=(), networks=(_NET, IPv4Network("172.17.0.0/16")))

    report = discover(scanner, networks=None, timeout=1.0)

    assert report.networks == (_NET,)
    assert report.skipped == (IPv4Network("172.17.0.0/16"),)


def test_a_named_network_that_is_too_large_is_refused_before_any_probe() -> None:
    scanner = FakeScanner(hits=())

    with pytest.raises(ValueError, match=f"more than {MAX_HOSTS}"):
        discover(scanner, networks=[IPv4Network("10.0.0.0/16")], timeout=1.0)
    assert scanner.probed == []


# ---------------------------------------------------------------- real scanner over loopback


class _GreetingServer:
    """Accepts one connection, sends ``greeting``, answers SYST, records what it received."""

    def __init__(self, greeting: bytes) -> None:
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port: int = self._listener.getsockname()[1]
        self._greeting = greeting
        self.received = b""
        self.done = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> _GreetingServer:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._listener.close()

    def _serve(self) -> None:
        connection, _ = self._listener.accept()
        with connection:
            connection.sendall(self._greeting)
            while chunk := connection.recv(1024):
                self.received += chunk
                if b"SYST" in chunk:
                    connection.sendall(b"215 Print Server FW 6022\r\n")
                if b"QUIT" in chunk:
                    break
        self.done.set()


@pytest.fixture
def closed_port() -> Iterator[int]:
    probe = socket.create_server(("127.0.0.1", 0))
    port: int = probe.getsockname()[1]
    probe.close()
    yield port


@pytest.mark.parametrize("greeting", [b"220 Print Server Ready.\r\n", b"220 ProFTPD Server ready.\r\n"])
def test_the_scanner_reads_the_greeting_and_sends_nothing_but_quit(greeting: bytes) -> None:
    with _GreetingServer(greeting) as server:
        hits = FtpBannerScanner(ftp_port=server.port).probe_ftp(["127.0.0.1"], timeout=5.0)
        server.done.wait()

    assert [(hit.host, hit.greeting) for hit in hits] == [(IPv4Address("127.0.0.1"), greeting.decode().strip())]
    assert server.received == b"QUIT\r\n"


def test_a_server_that_does_not_greet_with_220_is_left_out_and_still_told_quit() -> None:
    with _GreetingServer(b"421 Service not available.\r\n") as server:
        hits = FtpBannerScanner(ftp_port=server.port).probe_ftp(["127.0.0.1"], timeout=5.0)
        server.done.wait()

    assert hits == ()
    assert server.received == b"QUIT\r\n"


def test_a_host_with_nothing_listening_is_left_out(closed_port: int) -> None:
    assert FtpBannerScanner(ftp_port=closed_port).probe_ftp(["127.0.0.1"], timeout=1.0) == ()


def test_no_hosts_means_no_probe() -> None:
    assert FtpBannerScanner().probe_ftp([], timeout=1.0) == ()


# ---------------------------------------------------------------- CLI


def test_discover_answers_as_an_envelope(cli_runner: CliRunner) -> None:
    scanner = FakeScanner(hits=("192.0.2.3",), macs={"192.0.2.3": "00:c0:02:12:34:56"})

    result = cli_runner.invoke(
        cli_root.cli,
        ["discover", "--network", "192.0.2.0/29", "--json-bare"],
        obj=lambda: build_testing(scanner=scanner),
    )

    document = json.loads(result.output)
    assert result.exit_code == 0
    assert document["data"]["devices"] == [{"host": "192.0.2.3", "mac_address": "00:c0:02:12:34:56"}]


_OVERSIZED_NOTE = "172.17.0.0/16: more than 4096 addresses, name it with --network"


def test_discover_names_a_skipped_network_in_the_envelope(cli_runner: CliRunner) -> None:
    scanner = FakeScanner(hits=(), networks=(_NET, IPv4Network("172.17.0.0/16")))

    result = cli_runner.invoke(cli_root.cli, ["discover", "--json-bare"], obj=lambda: build_testing(scanner=scanner))

    document = json.loads(result.stdout)
    assert result.exit_code == 0
    assert document["skipped"] == [_OVERSIZED_NOTE]
    assert document["data"]["skipped"] == ["172.17.0.0/16"]


def test_discover_names_a_skipped_network_on_stderr_for_a_person(cli_runner: CliRunner) -> None:
    scanner = FakeScanner(hits=(), networks=(_NET, IPv4Network("172.17.0.0/16")))

    result = cli_runner.invoke(cli_root.cli, ["discover"], obj=lambda: build_testing(scanner=scanner))

    assert result.exit_code == 0
    assert result.stdout == "Searched 192.0.2.0/29 (6 addresses): 0 print server(s)\n"
    assert result.stderr == f"skipped {_OVERSIZED_NOTE}\n"


def test_discover_with_a_malformed_network_exits_22(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(cli_root.cli, ["discover", "--network", "192.0.2.0/33"], obj=build_testing)

    assert result.exit_code == 22
    assert "Error:" in result.output
