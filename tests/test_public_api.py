"""The package root is the library's public surface: what a Python caller imports."""

from __future__ import annotations

import pytest

import sercomm_printserver


@pytest.mark.os_agnostic
def test_every_exported_name_resolves() -> None:
    missing = [name for name in sercomm_printserver.__all__ if not hasattr(sercomm_printserver, name)]
    assert missing == []


@pytest.mark.os_agnostic
def test_open_print_server_returns_a_server_for_the_endpoint_without_contacting_it() -> None:
    server = sercomm_printserver.open_print_server(sercomm_printserver.DeviceEndpoint(host="192.0.2.52"))

    assert isinstance(server, sercomm_printserver.PrintServer)
    assert server.endpoint.host == "192.0.2.52"


@pytest.mark.os_agnostic
def test_discover_refuses_a_malformed_network_before_probing_anything() -> None:
    with pytest.raises(ValueError, match=r"192\.0\.2\.0/33"):
        sercomm_printserver.discover_print_servers(networks=["192.0.2.0/33"])


@pytest.mark.os_agnostic
def test_a_print_job_refuses_a_name_lpd_cannot_carry() -> None:
    with pytest.raises(ValueError, match="name"):
        sercomm_printserver.PrintJob(data=b"x", name="two words")
