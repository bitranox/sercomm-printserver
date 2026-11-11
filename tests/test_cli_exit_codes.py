"""Exit code integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sercomm_printserver.adapters import cli as cli_mod
from sercomm_printserver.adapters.cli.commands._device import exit_code_for
from sercomm_printserver.domain.errors import PrintSourceChangedError, SpoolError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from click.testing import CliRunner, Result


@pytest.mark.os_agnostic
def test_when_config_section_is_invalid_it_exits_with_code_22(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Config --section with nonexistent section must exit with INVALID_ARGUMENT (22)."""
    result: Result = cli_runner.invoke(
        cli_mod.cli, ["config", "--section", "nonexistent_section_that_does_not_exist"], obj=production_factory
    )

    assert result.exit_code == 22
    assert "not found" in result.stderr


@pytest.mark.os_agnostic
def test_when_config_deploy_has_permission_error_it_exits_with_code_13(
    cli_runner: CliRunner,
    inject_deploy_configuration: Callable[[Callable[..., list[Path]]], Callable[[], Any]],
) -> None:
    """Config-deploy PermissionError must exit with PERMISSION_DENIED (13)."""

    def mock_deploy(
        *,
        targets: Any,
        force: bool = False,
        profile: str | None = None,
        set_permissions: bool | None = None,
        dir_mode: int | None = None,
        file_mode: int | None = None,
        permission_overrides: Mapping[str, object] | None = None,
    ) -> list[Any]:
        raise PermissionError("Permission denied")

    factory = inject_deploy_configuration(mock_deploy)

    result: Result = cli_runner.invoke(cli_mod.cli, ["config-deploy", "--target", "app"], obj=factory)

    assert result.exit_code == 13
    assert "Permission denied" in result.stderr


@pytest.mark.os_agnostic
def test_when_config_deploy_has_generic_error_it_exits_with_code_1(
    cli_runner: CliRunner,
    inject_deploy_configuration: Callable[[Callable[..., list[Path]]], Callable[[], Any]],
) -> None:
    """Config-deploy generic Exception must exit with GENERAL_ERROR (1)."""

    def mock_deploy(
        *,
        targets: Any,
        force: bool = False,
        profile: str | None = None,
        set_permissions: bool | None = None,
        dir_mode: int | None = None,
        file_mode: int | None = None,
        permission_overrides: Mapping[str, object] | None = None,
    ) -> list[Any]:
        raise OSError("Disk full")

    factory = inject_deploy_configuration(mock_deploy)

    result: Result = cli_runner.invoke(cli_mod.cli, ["config-deploy", "--target", "user"], obj=factory)

    assert result.exit_code == 1
    assert "Disk full" in result.stderr


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("error", "code"),
    [
        # Nothing was sent: the job can be sent again once the temporary directory has room.
        (SpoolError("no space left in /tmp"), 74),
        # Part of the job may be on paper: a script must not resend it as it would a failure before the send.
        (PrintSourceChangedError("job.prn shrank"), 65),
    ],
)
def test_a_local_print_data_failure_has_its_own_exit_code(error: Exception, code: int) -> None:
    assert exit_code_for(error).value == code
