"""Unified EventLog — the single source of truth for robot events.

Replaces both the old EventLog (from mcp-ros-diagnosis) and the Episodic
layer (from memkit) with one canonical stream.

See docs/EVENTLOG_SCHEMA.md for the full specification.
"""
from __future__ import annotations

from mcp.eventlog.schema import EventLogEntry, Outcome, Severity, Source
from mcp.eventlog.writer import EventLogWriter
from mcp.eventlog.reader import EventLogReader

__all__ = [
    "EventLogEntry",
    "EventLogReader",
    "EventLogWriter",
    "Outcome",
    "Severity",
    "Source",
]
