"""TFTP adapter - RFC 1350 reads and action triggers without login.

Contents:
    * :class:`.client.TftpClient` - implements ``TftpPort``
"""

from __future__ import annotations

from .client import TftpClient

__all__ = ["TftpClient"]
