"""SNMP: the device's uptime, as the signal that a restart happened."""

from __future__ import annotations

from .uptime import SnmpUptime

__all__ = ["SnmpUptime"]
