"""Convert between a device's CONFIG text and :class:`~.config_model.DeviceConfig`.

``render_config(parse_config(text)) == text`` for a file the device produced: the parse keeps
every line it does not model, and the renderer spells every value and token as the firmware
does. That property is what makes writing a changed configuration back safe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from .config_lines import ConfigLine, join_lines, split_lines
from .config_reader import read_config
from .config_writer import write_config
from .errors import ConfigFormatError

if TYPE_CHECKING:
    from .config_model import DeviceConfig


class ConfigChange(BaseModel, frozen=True, extra="forbid"):
    """One parameter that differs between two configurations; ``None`` means absent."""

    number: int
    token: str
    old: str | None
    new: str | None


def parse_config(text: str) -> DeviceConfig:
    """Parse CONFIG text as the device delivers it.

    Raises:
        ConfigFormatError: The text is not a CONFIG file or a value is invalid.

    Example:
        >>> from pathlib import Path
        >>> SAMPLE = Path("docs/device-dump/CONFIG.txt").read_text(encoding="ascii")
        >>> config = parse_config(SAMPLE)
        >>> config.tcp_ip.dhcp
        False
    """
    return read_config(split_lines(text))


def render_config(config: DeviceConfig) -> str:
    """Render the configuration as the CONFIG text the device accepts.

    Example:
        >>> from pathlib import Path
        >>> SAMPLE = Path("docs/device-dump/CONFIG.txt").read_text(encoding="ascii")
        >>> render_config(parse_config(SAMPLE)) == SAMPLE
        True
    """
    return join_lines(write_config(config))


def config_lines(config: DeviceConfig) -> tuple[ConfigLine, ...]:
    """Return the configuration as its CONFIG lines, sorted by line number."""
    return write_config(config)


def diff_config(old: DeviceConfig, new: DeviceConfig) -> tuple[ConfigChange, ...]:
    """List the parameters whose rendered value differs, by line number.

    Example:
        >>> from pathlib import Path
        >>> SAMPLE = Path("docs/device-dump/CONFIG.txt").read_text(encoding="ascii")
        >>> before = parse_config(SAMPLE)
        >>> after = with_value(before, "BOX_NAME", "PRINTER2")
        >>> [(change.token, change.old, change.new) for change in diff_config(before, after)]
        [('BOX_NAME', 'PS_EXAMPLE', 'PRINTER2')]
    """
    before = {line.number: line for line in write_config(old)}
    after = {line.number: line for line in write_config(new)}
    changes = (_change(before.get(number), after.get(number)) for number in sorted(before.keys() | after.keys()))
    return tuple(change for change in changes if change is not None)


def _change(old: ConfigLine | None, new: ConfigLine | None) -> ConfigChange | None:
    reference = new if new is not None else old
    if reference is None:
        return None
    old_value = None if old is None else old.value
    new_value = None if new is None else new.value
    if old_value == new_value:
        return None
    return ConfigChange(number=reference.number, token=reference.token.strip(), old=old_value, new=new_value)


def find_line(config: DeviceConfig, key: str) -> ConfigLine:
    """Find a parameter by its token (``BOX_NAME``, case-insensitive) or 4-digit line number.

    Raises:
        ConfigFormatError: No parameter of this configuration matches ``key``.

    Example:
        >>> from pathlib import Path
        >>> SAMPLE = Path("docs/device-dump/CONFIG.txt").read_text(encoding="ascii")
        >>> find_line(parse_config(SAMPLE), "4020").token
        'DHCP_MODE'
    """
    wanted = key.strip()
    for line in write_config(config):
        if wanted.upper() == line.token.strip().upper() or (wanted.isdigit() and int(wanted) == line.number):
            return line
    raise ConfigFormatError(f"no parameter {key!r} in this configuration")


def with_value(config: DeviceConfig, key: str, value: str) -> DeviceConfig:
    """Return a copy of ``config`` with one parameter set from its CONFIG spelling.

    The value is validated exactly as if the device had reported it, so ``with_value`` refuses
    what the typed model refuses.

    Args:
        config: The configuration to change.
        key: Token or 4-digit line number of the parameter.
        value: The new value as written in a CONFIG file (``Enable``, ``192.0.2.10``, ...).

    Raises:
        ConfigFormatError: ``key`` does not name a parameter, or ``value`` is invalid for it.
    """
    target = find_line(config, key)
    lines = tuple(
        line.model_copy(update={"value": value.strip()}) if line.number == target.number else line
        for line in write_config(config)
    )
    return read_config(lines)


__all__ = [
    "ConfigChange",
    "config_lines",
    "diff_config",
    "find_line",
    "parse_config",
    "render_config",
    "with_value",
]
