"""The machine-readable answer every device command can give, and the one place that writes it.

Every command answers either for a person or, with ``--json`` (indented) or ``--json-bare``
(one line), as an envelope ``{ok, command, data, skipped}`` - the shape the sibling bitranox CLIs
use, so a skill or script reads all of them the same way. In machine mode stdout carries the
envelope and nothing else; anything said to a person goes to stderr. A failure is an
:class:`ErrorEnvelope` with the same ``ok`` and ``command`` keys, so a reader branches on one key.
Exit codes do not depend on the output format.

The payload is dumped where the envelope is built (:meth:`Envelope.of`), not declared as a
``BaseModel`` field: Pydantic serialises a field by its declared type, so a field typed as the
bare base class would dump every payload as ``{}``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from . import safe_console


class OutputMode(BaseModel):
    """Which of the shapes this invocation answers in, decided once from the two flags.

    Example:
        >>> OutputMode.of(as_json=False, as_json_bare=True)
        OutputMode(machine=True, indent=None)
    """

    model_config = ConfigDict(frozen=True)

    machine: bool
    indent: int | None

    @classmethod
    def of(cls, *, as_json: bool, as_json_bare: bool) -> OutputMode:
        """Return the mode the two click flags describe; bare implies machine."""
        return cls(machine=as_json or as_json_bare, indent=None if as_json_bare else 2)


class Envelope(BaseModel):
    """What a command reports when it ran; ``ok`` is False when the answer was no.

    ``skipped`` names anything the command did not do and why, so a partial answer is told
    apart from a complete one.
    """

    ok: bool
    command: str
    data: dict[str, Any]
    skipped: list[str] = []

    @classmethod
    def of(cls, *, command: str, payload: BaseModel, ok: bool = True, skipped: list[str] | None = None) -> Envelope:
        """Build the envelope around ``payload``, dumped in JSON mode.

        Example:
            >>> class Answer(BaseModel):
            ...     value: int
            >>> Envelope.of(command="x", payload=Answer(value=1)).model_dump_json()
            '{"ok":true,"command":"x","data":{"value":1},"skipped":[]}'
        """
        return cls(ok=ok, command=command, data=payload.model_dump(mode="json"), skipped=skipped or [])


class ErrorEnvelope(BaseModel):
    """What a command reports when it was refused or failed."""

    ok: bool = False
    command: str
    error: str
    message: str


def write_envelope(document: BaseModel, *, mode: OutputMode) -> None:
    """Write ``document`` as JSON to stdout, degrading what the console cannot encode."""
    safe_console.echo(document.model_dump_json(indent=mode.indent))


def report_failure(error: Exception, *, command: str, mode: OutputMode) -> None:
    """Report a refusal or failure: an error envelope in machine mode, one line on stderr otherwise."""
    if mode.machine:
        write_envelope(ErrorEnvelope(command=command, error=type(error).__name__, message=str(error)), mode=mode)
        return
    safe_console.echo(f"Error: {error}", err=True)


__all__ = ["Envelope", "ErrorEnvelope", "OutputMode", "report_failure", "write_envelope"]
