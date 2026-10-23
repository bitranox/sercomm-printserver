"""FTP adapter - the print server's configuration interface.

Contents:
    * :class:`.client.FtpClient` - implements ``FtpPort`` over active-mode FTP
"""

from __future__ import annotations

from .client import FtpClient

__all__ = ["FtpClient"]
