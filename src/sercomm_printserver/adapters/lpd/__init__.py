"""LPD adapter - RFC 1179 queue state and job submission on port 515.

Contents:
    * :class:`.client.LpdClient` - implements ``LpdPort``
"""

from __future__ import annotations

from .client import LpdClient

__all__ = ["LpdClient"]
