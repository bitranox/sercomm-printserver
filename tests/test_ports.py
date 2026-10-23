"""Port behavioral contract tests - verify in-memory adapter implementations.

Tests exercise in-memory adapters only - production adapters are tested
via CLI integration tests. Static type conformance is enforced by pyright.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from lib_layered_config import Config

from sercomm_printserver.adapters.memory import (
    check_logging_config_in_memory,
    get_config_in_memory,
    get_default_config_path_in_memory,
    init_logging_in_memory,
)

if TYPE_CHECKING:
    from sercomm_printserver.application.ports import (
        CheckLoggingConfig,
        GetConfig,
        GetDefaultConfigPath,
        InitLogging,
    )
    from sercomm_printserver.composition import AppServices


# ======================== In-Memory Adapter Contract Tests ========================


@pytest.fixture
def get_config_impl() -> GetConfig:
    """Provide in-memory GetConfig implementation."""
    return get_config_in_memory


@pytest.fixture
def get_default_config_path_impl() -> GetDefaultConfigPath:
    """Provide in-memory GetDefaultConfigPath implementation."""
    return get_default_config_path_in_memory


@pytest.fixture
def init_logging_impl() -> InitLogging:
    """Provide in-memory InitLogging implementation."""
    return init_logging_in_memory


@pytest.fixture
def check_logging_config_impl() -> CheckLoggingConfig:
    """Provide in-memory CheckLoggingConfig implementation."""
    return check_logging_config_in_memory


@pytest.mark.os_agnostic
def test_get_config_returns_config_with_dict(get_config_impl: GetConfig) -> None:
    """GetConfig must return a Config whose as_dict() yields a dict."""
    config = get_config_impl()
    assert isinstance(config, Config)
    assert isinstance(config.as_dict(), dict)


@pytest.mark.os_agnostic
def test_get_default_config_path_returns_toml_path(get_default_config_path_impl: GetDefaultConfigPath) -> None:
    """GetDefaultConfigPath must return a Path ending in .toml."""
    path = get_default_config_path_impl()
    assert isinstance(path, Path)
    assert path.suffix == ".toml"


@pytest.mark.os_agnostic
def test_init_logging_does_not_raise(init_logging_impl: InitLogging) -> None:
    """InitLogging must not raise when called with a Config."""
    config = Config({}, {})
    init_logging_impl(config)


@pytest.mark.os_agnostic
def test_check_logging_config_in_memory_refuses_nothing(check_logging_config_impl: CheckLoggingConfig) -> None:
    """The test runtime ignores the configuration, so no logging section can break it."""
    check_logging_config_impl(Config({"lib_log_rich": {"rate_limit": "100:60"}}, {}))


# ======================== Composition Wiring Tests ========================


@pytest.mark.os_agnostic
def test_build_production_returns_fully_populated_app_services() -> None:
    """build_production() must return AppServices with all fields populated."""
    from sercomm_printserver.composition import AppServices, build_production

    services = build_production()
    assert isinstance(services, AppServices)
    for field_obj in services.__dataclass_fields__:
        assert getattr(services, field_obj) is not None


@pytest.mark.os_agnostic
def test_build_testing_returns_fully_populated_app_services() -> None:
    """build_testing() must return AppServices with all in-memory implementations."""
    from sercomm_printserver.composition import AppServices, build_testing

    services = build_testing()
    assert isinstance(services, AppServices)
    for field_obj in services.__dataclass_fields__:
        assert getattr(services, field_obj) is not None


@pytest.mark.os_agnostic
def test_build_production_services_are_callable() -> None:
    """All services from build_production() must be callable."""
    from sercomm_printserver.composition import build_production

    services = build_production()
    _assert_every_port_is_usable(services)


@pytest.mark.os_agnostic
def test_build_testing_services_are_callable() -> None:
    """All services from build_testing() must be callable."""
    from sercomm_printserver.composition import build_testing

    services = build_testing()
    _assert_every_port_is_usable(services)


#: Ports that are objects with several methods rather than one callable, and those methods.
_OBJECT_PORTS = {"host_scanner": ("local_networks", "probe_ftp", "mac_address")}


def _assert_every_port_is_usable(services: AppServices) -> None:
    for field in dataclasses.fields(services):
        port = getattr(services, field.name)
        methods = _OBJECT_PORTS.get(field.name)
        if methods is None:
            assert callable(port), field.name
        else:
            assert all(callable(getattr(port, method)) for method in methods), field.name
