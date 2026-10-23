"""What a print server says about itself: the ``PSINF`` file and the FTP ``SYST`` reply.

``PSINF`` is a short report: a few ``Key: Value`` lines, then sections (``Netware Info:``,
``TCP/IP Info:``, ...) whose entries are indented. The device ends it with CRLF line endings
and a form feed. Every entry is kept, so nothing the device reports is lost; the fields a
caller needs most are lifted into typed attributes.
"""

from __future__ import annotations

import re
from ipaddress import AddressValueError, IPv4Address
from typing import Final

from pydantic import BaseModel

from .errors import DeviceResponseError

#: Every SerComm unit's default name is "SC" plus the last three bytes of its MAC address; the
#: first three are SerComm's vendor prefix.
_DEFAULT_NAME: Final = re.compile(r"SC([0-9A-F]{6})", re.IGNORECASE)
_SERCOMM_OUI: Final = "00:c0:02"
_SYST_REPLY: Final = re.compile(r"215 Print Server FW (?P<version>.*)")
#: What a firmware version looks like: 6022, 6A10. Firmware 6A10 answers SYST with random
#: bytes in place of its version, so anything else is no version at all.
_VERSION: Final = re.compile(r"[0-9A-Za-z.]{1,16}")


class InfoEntry(BaseModel, frozen=True, extra="forbid"):
    """One ``Key: Value`` line of the report."""

    key: str
    value: str


class InfoSection(BaseModel, frozen=True, extra="forbid"):
    """A titled block of indented entries, such as ``TCP/IP Info``."""

    title: str
    entries: tuple[InfoEntry, ...]


class DeviceInfo(BaseModel, frozen=True, extra="forbid"):
    """The device's self-description from ``PSINF``.

    Example:
        >>> from pathlib import Path
        >>> info = parse_psinf(Path("docs/device-dump/PSINF.txt").read_text(encoding="ascii"))
        >>> info.firmware_version, info.mac_address, str(info.ip_address)
        ('6022', '00:c0:02:12:34:56', '192.0.2.52')
    """

    hardware_id: str
    firmware_version: str
    protocol_id: str
    default_name: str
    server_name: str
    mac_address: str | None
    ip_address: IPv4Address | None
    subnet_mask: IPv4Address | None
    gateway: IPv4Address | None
    general: tuple[InfoEntry, ...]
    sections: tuple[InfoSection, ...]


def mac_from_default_name(default_name: str) -> str | None:
    """Derive the MAC address from a default name ``SCxxyyzz``, or None for any other name.

    Example:
        >>> mac_from_default_name("SC123456")
        '00:c0:02:12:34:56'
        >>> mac_from_default_name("PS1A2B3C") is None
        True
    """
    match = _DEFAULT_NAME.fullmatch(default_name)
    if match is None:
        return None
    tail = match[1].lower()
    return ":".join([_SERCOMM_OUI, tail[0:2], tail[2:4], tail[4:6]])


def parse_firmware_reply(reply: str) -> str:
    """Return the firmware version from the FTP ``SYST`` reply.

    Raises:
        DeviceResponseError: The reply is not the print server's ``215`` answer, or it carries
            no readable version.

    Example:
        >>> parse_firmware_reply("215 Print Server FW 6022")
        '6022'
    """
    match = _SYST_REPLY.fullmatch(reply.strip())
    if match is None:
        raise DeviceResponseError(f"unexpected SYST reply {reply.strip()[:60]!r}")
    if _VERSION.fullmatch(match["version"]) is None:
        raise DeviceResponseError(f"SYST reply carries no readable firmware version: {match['version']!r}")
    return match["version"]


def parse_psinf(text: str) -> DeviceInfo:
    """Parse the ``PSINF`` report.

    Raises:
        DeviceResponseError: A line is not ``Key: Value`` or a required header line is missing.
    """
    general, sections = _split_report(text)
    head = {entry.key: entry.value for entry in general}
    tcp = {
        entry.key: entry.value for section in sections if section.title == "TCP/IP Info" for entry in section.entries
    }
    default_name = _required(head, "Default Name")
    return DeviceInfo(
        hardware_id=_required(head, "Hardware ID"),
        firmware_version=_required(head, "Firmware Version"),
        protocol_id=_required(head, "Protocol ID"),
        default_name=default_name,
        server_name=_required(head, "Server Name"),
        mac_address=mac_from_default_name(default_name),
        ip_address=_address(tcp.get("IP Address")),
        subnet_mask=_address(tcp.get("Subnet Mask")),
        gateway=_address(tcp.get("Gateway Address")),
        general=general,
        sections=sections,
    )


def _split_report(text: str) -> tuple[tuple[InfoEntry, ...], tuple[InfoSection, ...]]:
    general: list[InfoEntry] = []
    sections: list[InfoSection] = []
    title: str | None = None
    entries: list[InfoEntry] = []
    for raw in text.replace("\x0c", "").splitlines():
        if not raw.strip():
            continue
        entry = _entry(raw)
        if raw[:1].isspace() and title is not None:
            entries.append(entry)
        elif not entry.value and raw.rstrip().endswith(":"):
            if title is not None:
                sections.append(InfoSection(title=title, entries=tuple(entries)))
            title, entries = entry.key, []
        else:
            general.append(entry)
    if title is not None:
        sections.append(InfoSection(title=title, entries=tuple(entries)))
    return tuple(general), tuple(sections)


def _entry(raw: str) -> InfoEntry:
    key, separator, value = raw.strip().partition(":")
    if not separator or not key:
        raise DeviceResponseError(f"PSINF line is not 'Key: Value': {raw.strip()[:60]!r}")
    return InfoEntry(key=key.strip(), value=value.strip())


def _required(entries: dict[str, str], key: str) -> str:
    if key not in entries:
        raise DeviceResponseError(f"PSINF has no {key!r} line")
    return entries[key]


def _address(value: str | None) -> IPv4Address | None:
    if not value:
        return None
    try:
        return IPv4Address(value)
    except AddressValueError:
        return None


__all__ = [
    "DeviceInfo",
    "InfoEntry",
    "InfoSection",
    "mac_from_default_name",
    "parse_firmware_reply",
    "parse_psinf",
]
