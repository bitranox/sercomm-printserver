"""Probe hosts' FTP port concurrently; find MAC addresses and local networks with ipscout.

A probe connects, reads the greeting, and only when it is the print server family's greeting
asks ``SYST`` for the firmware; any other FTP server gets nothing but ``QUIT``. It never logs in
and never touches a print port. ipscout reads the neighbour cache passively (no privileges), and
the probe's own connection is what put the device there.
"""

from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from ipaddress import IPv4Address, IPv4Network
from typing import TYPE_CHECKING, Final

import ipscout

from ...application.discovery import PRINT_SERVER_GREETING, ProbeHit

if TYPE_CHECKING:
    from collections.abc import Sequence

#: An FTP reply line is short; more than this without a line end is not an FTP server.
_LINE_LIMIT: Final = 512


class FtpBannerScanner:
    """Implements :class:`~sercomm_printserver.application.ports.HostScanner`.

    Args:
        workers: Probes in flight at once.
        ftp_port: Port to probe; 21 on a real device, anything for a test server.
    """

    def __init__(self, *, workers: int = 64, ftp_port: int = 21) -> None:
        self._workers = workers
        self._ftp_port = ftp_port

    def local_networks(self) -> tuple[IPv4Network, ...]:
        """Return the IPv4 networks this host holds an address in (ipscout's sweep view)."""
        return ipscout.local_networks()

    def probe_ftp(self, hosts: Sequence[str], *, timeout: float) -> tuple[ProbeHit, ...]:
        """Probe ``hosts`` concurrently; return the ones that greeted."""
        if not hosts:
            return ()
        probe = partial(self._probe, timeout=timeout)
        with ThreadPoolExecutor(max_workers=min(self._workers, len(hosts))) as pool:
            results = list(pool.map(probe, hosts))
        return tuple(hit for hit in results if hit is not None)

    def mac_address(self, host: str) -> str | None:
        """Return the MAC this host's neighbour cache holds for ``host``, or None."""
        try:
            return ipscout.get_mac_address(host)
        except (ipscout.IPScoutError, ValueError):
            return None

    def _probe(self, host: str, *, timeout: float) -> ProbeHit | None:
        try:
            connection = socket.create_connection((host, self._ftp_port), timeout=timeout)
        except OSError:
            return None
        with connection:
            return _converse(connection, host)


def _converse(connection: socket.socket, host: str) -> ProbeHit | None:
    try:
        greeting = _read_line(connection)
        if not greeting.startswith("220"):
            return None
        reply = ""
        if greeting.startswith(PRINT_SERVER_GREETING):
            connection.sendall(b"SYST\r\n")
            reply = _read_line(connection)
        connection.sendall(b"QUIT\r\n")
    except OSError:
        return None
    return ProbeHit(host=IPv4Address(host), greeting=greeting, system_reply=reply)


def _read_line(connection: socket.socket) -> str:
    data = b""
    while b"\n" not in data and len(data) < _LINE_LIMIT:
        chunk = connection.recv(_LINE_LIMIT)
        if not chunk:
            break
        data += chunk
    return data.split(b"\n", 1)[0].decode("ascii", errors="replace").strip()


__all__ = ["FtpBannerScanner"]
