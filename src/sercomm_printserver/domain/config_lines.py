"""The CONFIG file as lines: ``NNNN TOKEN:VALUE``, one parameter each.

This is the format layer only - splitting text into numbered lines and joining them back.
What a value means is :mod:`.config_codec`'s business.

The device writes LF line endings, no blank lines and no comments, and the vendor manual says
the device skips any line that does not start with a digit; that is what the parser does too.
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, Field

from .errors import ConfigFormatError

#: Four digits, a space, the token up to the first colon, the value. The manual calls the token
#: optional; the colon is what separates it from the value.
_LINE: Final = re.compile(r"(?P<number>[0-9]{4}) ?(?P<token>[^:\r\n]*):(?P<value>[^\r\n]*)")


class ConfigLine(BaseModel, frozen=True, extra="forbid"):
    """One parameter line exactly as the device prints it."""

    number: int = Field(ge=0, le=9999)
    token: str
    value: str

    def render(self) -> str:
        """Return the line as the device prints it, without the line ending.

        Example:
            >>> ConfigLine(number=12, token="TCPIP_P ", value="Enable").render()
            '0012 TCPIP_P :Enable'
        """
        return f"{self.number:04d} {self.token}:{self.value}"


def split_lines(text: str) -> tuple[ConfigLine, ...]:
    """Split CONFIG text into its parameter lines, in file order.

    Args:
        text: The CONFIG file as text.

    Returns:
        One :class:`ConfigLine` per parameter line.

    Raises:
        ConfigFormatError: A line starts with a digit but is not ``NNNN TOKEN:VALUE``, or a
            line number occurs twice.

    Example:
        >>> [line.number for line in split_lines("0001 BOX_NAME:X\\n0011 IPXSPX_P:Disable\\n")]
        [1, 11]
    """
    lines: list[ConfigLine] = []
    seen: set[int] = set()
    for index, raw in enumerate(text.splitlines(), start=1):
        if not raw[:1].isdigit():
            continue
        line = _parse_line(raw, index=index)
        if line.number in seen:
            raise ConfigFormatError(f"line {index}: parameter {line.number:04d} appears twice")
        seen.add(line.number)
        lines.append(line)
    return tuple(lines)


def _parse_line(raw: str, *, index: int) -> ConfigLine:
    match = _LINE.fullmatch(raw)
    if match is None:
        raise ConfigFormatError(f"line {index}: expected 'NNNN TOKEN:VALUE', got {raw[:40]!r}")
    return ConfigLine(number=int(match["number"]), token=match["token"], value=match["value"].strip())


def join_lines(lines: tuple[ConfigLine, ...]) -> str:
    """Join parameter lines into CONFIG text, sorted by line number, LF-terminated.

    Example:
        >>> join_lines((ConfigLine(number=11, token="IPXSPX_P", value="Disable"),
        ...             ConfigLine(number=1, token="BOX_NAME", value="X")))
        '0001 BOX_NAME:X\\n0011 IPXSPX_P:Disable\\n'
    """
    return "".join(f"{line.render()}\n" for line in sorted(lines, key=lambda line: line.number))


__all__ = ["ConfigLine", "join_lines", "split_lines"]
