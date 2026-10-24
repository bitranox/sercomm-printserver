"""The envelope's ``command`` key: a closed set of names that are real click command paths.

The names are an Enum so a command cannot report a label nobody can type; these tests pin that
the wire value is the plain command path and that every name still resolves to a registered
click command, so the Enum and the command tree cannot drift apart.
"""

from __future__ import annotations

import click
from pydantic import BaseModel

from sercomm_printserver.adapters.cli import root as cli_root
from sercomm_printserver.adapters.cli.constants import CommandName
from sercomm_printserver.adapters.cli.envelope import Envelope, ErrorEnvelope


class _Answer(BaseModel):
    value: int


def _command_paths(group: click.Group, *, prefix: str = "") -> set[str]:
    """Every command path below ``group``, groups included, as typed after the program name."""
    paths: set[str] = set()
    for name, command in group.commands.items():
        path = f"{prefix}{name}"
        paths.add(path)
        if isinstance(command, click.Group):
            paths |= _command_paths(command, prefix=f"{path} ")
    return paths


def test_every_command_name_is_a_registered_click_command_path() -> None:
    registered = _command_paths(cli_root.cli)

    unregistered = sorted(name.value for name in CommandName if name.value not in registered)

    assert len(registered) > len(CommandName)
    assert unregistered == []


def test_the_command_name_reaches_the_wire_as_its_plain_path() -> None:
    envelope = Envelope.of(command=CommandName.CREDENTIAL_SET, payload=_Answer(value=1))

    assert envelope.model_dump_json() == '{"ok":true,"command":"password set","data":{"value":1},"skipped":[]}'


def test_an_error_envelope_carries_the_same_plain_path() -> None:
    envelope = ErrorEnvelope(command=CommandName.DEVICE_CONFIG_SET, error="ValueError", message="bad")

    assert envelope.model_dump_json() == (
        '{"ok":false,"command":"device-config set","error":"ValueError","message":"bad"}'
    )
