"""The package root is the library's public surface: what a Python caller imports."""

from __future__ import annotations

from enum import Enum

import pytest

import sercomm_printserver
from sercomm_printserver.domain import errors


@pytest.mark.os_agnostic
def test_every_exported_name_resolves() -> None:
    missing = [name for name in sercomm_printserver.__all__ if not hasattr(sercomm_printserver, name)]
    assert missing == []


@pytest.mark.os_agnostic
def test_every_exception_the_library_raises_can_be_imported_from_the_package() -> None:
    defined = {
        name
        for name, value in vars(errors).items()
        if isinstance(value, type) and issubclass(value, Exception) and value.__module__ == errors.__name__
    }

    assert defined, "found no exceptions, so this test checked nothing"
    assert defined - set(sercomm_printserver.__all__) == set()


@pytest.mark.os_agnostic
def test_every_enum_a_port_status_holds_can_be_imported_from_the_package() -> None:
    annotations = (field.annotation for field in sercomm_printserver.PortStatus.model_fields.values())
    held = {value.__name__ for value in annotations if isinstance(value, type) and issubclass(value, Enum)}

    assert held, "found no enums, so this test checked nothing"
    assert held - set(sercomm_printserver.__all__) == set()


@pytest.mark.os_agnostic
def test_open_print_server_returns_a_server_for_the_endpoint_without_contacting_it() -> None:
    server = sercomm_printserver.open_print_server(sercomm_printserver.DeviceEndpoint(host="192.0.2.52"))

    assert isinstance(server, sercomm_printserver.PrintServer)
    assert server.endpoint.host == "192.0.2.52"


@pytest.mark.os_agnostic
def test_discover_refuses_a_malformed_network_before_probing_anything() -> None:
    with pytest.raises(ValueError, match=r"'192\.0\.2\.0/33' is not an IPv4 network"):
        sercomm_printserver.discover_print_servers(networks=["192.0.2.0/33"])


@pytest.mark.os_agnostic
def test_a_print_job_refuses_a_name_lpd_cannot_carry() -> None:
    with pytest.raises(ValueError, match=r"name\n +String should match pattern"):
        sercomm_printserver.PrintJob(data=b"x", name="two words")
