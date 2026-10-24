"""What every device command shares: its options, how it reaches the device, how it answers.

A command supplies only the work (a function of a
:class:`~sercomm_printserver.application.print_server.PrintServer`) and how to say the result
to a person. :func:`run_device_command` resolves the device from ``[device]`` and the flags,
runs the work, prints the envelope or the human text, and turns the known failures into their
exit codes, so all commands report the same failure the same way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

import lib_log_rich.runtime
import rich_click as click
from pydantic import BaseModel

from sercomm_printserver.adapters.config.device_settings import load_device_settings, resolve_endpoint
from sercomm_printserver.domain.errors import (
    AuthenticationRequiredError,
    ConfigurationError,
    ConfirmationRequiredError,
    DeviceResponseError,
    DeviceUnavailableError,
    HostPrivilegeError,
    NeighborTableError,
)

from .. import safe_console
from ..config_load import require_config
from ..context import get_cli_context
from ..envelope import Envelope, OutputMode, report_failure, write_envelope
from ..exit_codes import ExitCode
from ..typed_click import option

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from sercomm_printserver.adapters.config.device_settings import DeviceSettings
    from sercomm_printserver.application.print_server import PrintServer
    from sercomm_printserver.composition import AppServices
    from sercomm_printserver.domain.endpoint import DeviceEndpoint

    from ..constants import CommandName

_P = TypeVar("_P", bound="BaseModel")
_F = TypeVar("_F", bound="Callable[..., Any]")

#: Known failures and their exit codes, most specific first: DeviceResponseError and
#: ConfigFormatError are both ValueErrors, and the refusals and HostPrivilegeError are all
#: PermissionErrors - only the last says THIS host lacks a right, so it alone exits 13.
_EXIT_CODES: tuple[tuple[type[Exception], ExitCode], ...] = (
    (ConfigurationError, ExitCode.CONFIG_ERROR),
    (DeviceUnavailableError, ExitCode.DEVICE_UNAVAILABLE),
    (DeviceResponseError, ExitCode.PROTOCOL_ERROR),
    (HostPrivilegeError, ExitCode.PERMISSION_DENIED),
    (NeighborTableError, ExitCode.GENERAL_ERROR),
    (AuthenticationRequiredError, ExitCode.REFUSED),
    (ConfirmationRequiredError, ExitCode.REFUSED),
    (ValueError, ExitCode.INVALID_ARGUMENT),
)
_HANDLED: tuple[type[Exception], ...] = tuple(error_type for error_type, _ in _EXIT_CODES)


def exit_code_for(error: Exception) -> ExitCode:
    """Return the exit code a known failure maps to.

    Example:
        >>> exit_code_for(DeviceUnavailableError("down")).value
        69
    """
    for error_type, code in _EXIT_CODES:
        if isinstance(error, error_type):
            return code
    return ExitCode.GENERAL_ERROR


def device_options(command: _F) -> _F:
    """Add ``--host``, ``--timeout``, ``--json`` and ``--json-bare`` to a device command."""
    host = option("--host", type=str, default=None, help="Print server address (overrides [device] host).")
    wrapped: Any = host(session_options(command))
    return wrapped


def session_options(command: _F) -> _F:
    """Add ``--timeout``, ``--json`` and ``--json-bare``: what a command that names its own address needs."""
    decorators = (
        option(
            "--timeout",
            type=click.FloatRange(min=0.1, max=600),
            default=None,
            help="Network timeout per operation in seconds (overrides [device] timeout).",
        ),
        option("--json", "as_json", is_flag=True, default=False, help="Answer as an indented JSON envelope."),
        option("--json-bare", "as_json_bare", is_flag=True, default=False, help="Answer as one-line JSON."),
    )
    wrapped: Any = command
    for decorator in reversed(decorators):
        wrapped = decorator(wrapped)
    return wrapped


def run_device_command(
    ctx: click.Context,
    *,
    command: CommandName,
    flags: DeviceFlags,
    work: Callable[[PrintServer], _P],
    human: Callable[[_P], str],
) -> None:
    """Run ``work`` against the configured device and answer in the requested shape."""

    def on_endpoint(endpoint: DeviceEndpoint, services: AppServices, settings: DeviceSettings) -> _P:
        return work(services.open_print_server(endpoint, raw_port_base=settings.raw_port_base))

    run_endpoint_command(ctx, command=command, flags=flags, work=on_endpoint, human=human)


def run_endpoint_command(
    ctx: click.Context,
    *,
    command: CommandName,
    flags: DeviceFlags,
    work: Callable[[DeviceEndpoint, AppServices, DeviceSettings], _P],
    human: Callable[[_P], str],
) -> None:
    """Like :func:`run_device_command`, for work that needs the endpoint and services themselves.

    The ARP trick opens the print server only after this host maps the borrowed address, so it
    takes the endpoint (``flags.host`` is that address) instead of a ready server.
    """
    mode = OutputMode.of(as_json=flags.as_json, as_json_bare=flags.as_json_bare)
    cli_ctx = get_cli_context(ctx)
    config = require_config(ctx, cli_ctx)
    with lib_log_rich.runtime.bind(job_id=f"cli-{command.value}", extra={"command": command.value}):
        try:
            settings = load_device_settings(config)
            endpoint = resolve_endpoint(settings, host=flags.host, timeout=flags.timeout)
            payload = work(endpoint, cli_ctx.services, settings)
        except _HANDLED as error:
            report_failure(error, command=command, mode=mode)
            ctx.exit(exit_code_for(error))
    if mode.machine:
        write_envelope(Envelope.of(command=command, payload=payload), mode=mode)
    else:
        safe_console.echo(human(payload))


class DeviceFlags(BaseModel, frozen=True, extra="forbid"):
    """The four options :func:`device_options` adds, as one value."""

    host: str | None
    timeout: float | None
    as_json: bool
    as_json_bare: bool


__all__ = [
    "DeviceFlags",
    "device_options",
    "exit_code_for",
    "run_device_command",
    "run_endpoint_command",
    "session_options",
]
