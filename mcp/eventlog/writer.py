"""EventLog writer — appends JSONL to daily rotating files."""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mcp.eventlog.schema import EventLogEntry, Outcome, Severity, Source


class EventLogWriter:
    """Thread-safe append-only writer. One writer per process per robot.

    Writes to <root>/YYYY-MM-DD.jsonl. Rotates daily on UTC boundaries.
    """

    def __init__(
        self,
        root: str | Path,
        robot_id: str,
        session_id: Optional[str] = None,
        buffer_size: int = 1,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.robot_id = robot_id
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self._seq = 0
        self._task_id: Optional[str] = None
        self._lock = threading.Lock()
        self._buffer: list[str] = []
        self._buffer_size = buffer_size
        self._current_file: Optional[Path] = None
        self._fp = None

    def _path_for(self, dt: datetime) -> Path:
        return self.root / f"{dt.strftime('%Y-%m-%d')}.jsonl"

    def _rotate_if_needed(self) -> None:
        now = datetime.now(timezone.utc)
        target = self._path_for(now)
        if self._current_file != target:
            if self._fp is not None:
                self._fp.close()
            self._fp = open(target, "a", encoding="utf-8")
            self._current_file = target

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def bind_task(self, task_id: str) -> None:
        with self._lock:
            self._task_id = task_id

    def unbind_task(self) -> None:
        with self._lock:
            self._task_id = None

    def write(self, entry: EventLogEntry) -> None:
        with self._lock:
            self._rotate_if_needed()
            self._buffer.append(entry.to_jsonl())
            if len(self._buffer) >= self._buffer_size:
                self._flush_locked()

    def _flush_locked(self) -> None:
        if not self._buffer or self._fp is None:
            return
        self._fp.write("\n".join(self._buffer) + "\n")
        self._fp.flush()
        self._buffer.clear()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def close(self) -> None:
        self.flush()
        with self._lock:
            if self._fp is not None:
                self._fp.close()
                self._fp = None

    def _make_entry(
        self,
        source: Source,
        payload_key: str,
        payload: dict[str, Any],
        severity: Severity = "info",
        tags: Optional[list[str]] = None,
    ) -> EventLogEntry:
        return EventLogEntry(
            ts=EventLogEntry.now_ts(),
            seq=self._next_seq(),
            session_id=self.session_id,
            robot_id=self.robot_id,
            task_id=self._task_id,
            source=source,
            severity=severity,
            tags=tags or [],
            **{payload_key: payload},
        )

    def write_physical(
        self,
        snapshot: dict[str, Any],
        severity: Severity = "info",
        tags: Optional[list[str]] = None,
    ) -> None:
        self.write(self._make_entry("physical", "physical", snapshot, severity, tags))

    def write_cognitive(
        self,
        event: dict[str, Any],
        severity: Severity = "info",
        tags: Optional[list[str]] = None,
    ) -> None:
        self.write(self._make_entry("cognitive", "cognitive", event, severity, tags))

    def write_safety(
        self,
        event: dict[str, Any],
        severity: Severity = "warn",
        tags: Optional[list[str]] = None,
    ) -> None:
        self.write(self._make_entry("safety", "safety", event, severity, tags))

    def write_command(
        self,
        cmd: dict[str, Any],
        severity: Severity = "info",
        tags: Optional[list[str]] = None,
    ) -> None:
        self.write(self._make_entry("command", "command", cmd, severity, tags))

    def set_outcome(
        self,
        task_id: str,
        outcome: Outcome,
        failure_reason: Optional[str] = None,
        failure_phenomenon: Optional[str] = None,
    ) -> None:
        """Append a task-end entry that labels outcome for the given task_id."""
        entry = EventLogEntry(
            ts=EventLogEntry.now_ts(),
            seq=self._next_seq(),
            session_id=self.session_id,
            robot_id=self.robot_id,
            task_id=task_id,
            source="cognitive",
            severity="info" if outcome == "success" else "warn",
            tags=["task_end"],
            outcome=outcome,
            failure_reason=failure_reason,
            failure_phenomenon=failure_phenomenon,
        )
        self.write(entry)

    def __enter__(self) -> "EventLogWriter":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
