"""Tests for the logging configuration model.

LoggingConfigModel is lib_log_rich's RuntimeConfig, read once from the ``[lib_log_rich]``
section. The init_logging function is tested via CLI integration tests in test_cli_core.py.
"""

from __future__ import annotations

import lib_log_rich.runtime
import pytest
from pydantic import ValidationError

from sercomm_printserver import __init__conf__
from sercomm_printserver.adapters.logging.setup import LoggingConfigModel


@pytest.mark.os_agnostic
def test_the_section_is_parsed_into_the_runtime_config_lib_log_rich_consumes() -> None:
    parsed = LoggingConfigModel.model_validate({"service": "test", "environment": "dev", "console_level": "debug"})

    assert isinstance(parsed, lib_log_rich.runtime.RuntimeConfig)
    assert (parsed.service, parsed.environment, parsed.console_level) == ("test", "dev", "debug")
    lib_log_rich.runtime.validate_config(parsed)


@pytest.mark.os_agnostic
def test_a_key_lib_log_rich_does_not_know_is_ignored() -> None:
    parsed = LoggingConfigModel.model_validate({"service": "test", "custom_field": "value"})

    assert "custom_field" not in parsed.model_dump()


@pytest.mark.os_agnostic
@pytest.mark.parametrize("section", [{}, [], "", None])
def test_an_empty_section_gives_the_package_defaults(section: object) -> None:
    parsed = LoggingConfigModel.model_validate(section)

    assert parsed.service == __init__conf__.name
    assert parsed.environment == "prod"


@pytest.mark.os_agnostic
@pytest.mark.parametrize("service", ["", None])
def test_an_empty_or_null_service_names_the_package(service: str | None) -> None:
    assert LoggingConfigModel.model_validate({"service": service}).service == __init__conf__.name


@pytest.mark.os_agnostic
def test_a_null_setting_leaves_lib_log_rich_s_default_in_place() -> None:
    parsed = LoggingConfigModel.model_validate({"console_theme": None, "enable_ring_buffer": None})

    default = lib_log_rich.runtime.RuntimeConfig(service="x", environment="y")
    assert parsed.console_theme == default.console_theme
    assert parsed.enable_ring_buffer == default.enable_ring_buffer


@pytest.mark.os_agnostic
def test_a_null_environment_is_refused() -> None:
    with pytest.raises(ValidationError) as caught:
        LoggingConfigModel.model_validate({"environment": None})

    assert [(e["loc"], e["msg"]) for e in caught.value.errors()] == [
        (("environment",), "Input should be a valid string")
    ]


@pytest.mark.os_agnostic
def test_a_section_that_is_not_a_table_is_refused() -> None:
    with pytest.raises(ValidationError) as caught:
        LoggingConfigModel.model_validate("x")

    assert [e["msg"] for e in caught.value.errors()] == [
        "Input should be a valid dictionary or instance of LoggingConfigModel"
    ]


@pytest.mark.os_agnostic
def test_a_wrong_type_for_a_lib_log_rich_setting_is_refused_by_lib_log_rich_s_own_field() -> None:
    with pytest.raises(ValidationError) as caught:
        LoggingConfigModel.model_validate({"rate_limit": "100:60"})

    assert [(e["loc"], e["msg"]) for e in caught.value.errors()] == [(("rate_limit",), "Input should be a valid tuple")]
