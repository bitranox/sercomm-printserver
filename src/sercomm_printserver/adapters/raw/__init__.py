"""RAW adapter: direct-socket printing to the print server's RAW TCP ports."""

from __future__ import annotations

from .printer import RawPrinter, connect_retrying_refusals

__all__ = ["RawPrinter", "connect_retrying_refusals"]
