from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from eventlog import EventLogReader
from eventlog.schema import EventLogEntry


@dataclass
class TaskAggregate:
    """Aggregated stats for a single task_id.

    Mirrors the shape emitted by ``snakes score`` so callers (CLI, matrix
    scripts, dashboards) share one canonical aggregation.
    """

    task_id: str
    outcome: Optional[str] = None
    score: Optional[dict[str, Any]] = None
    failure_counts: dict[str, int] = field(default_factory=dict)
    failure_latency_ms: dict[str, int] = field(default_factory=dict)
    timeouts: int = 0
    retry_attempts_total: int = 0
    tool_latency_ms_total: int = 0
    tool_latency_by_group: dict[str, int] = field(default_factory=dict)
    events: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "outcome": self.outcome,
            "score": self.score,
            "failure_counts": self.failure_counts,
            "failure_latency_ms": self.failure_latency_ms,
            "timeouts": self.timeouts,
            "retry_attempts_total": self.retry_attempts_total,
            "tool_latency_ms_total": self.tool_latency_ms_total,
            "tool_latency_by_group": self.tool_latency_by_group,
            "events": self.events,
        }


def aggregate_entries(
    task_id: str,
    entries: Iterable[EventLogEntry],
    *,
    reader_outcome: Optional[tuple[str, Optional[str]]] = None,
) -> TaskAggregate:
    agg = TaskAggregate(task_id=task_id)
    entries_list = list(entries)
    agg.events = len(entries_list)

    for e in reversed(entries_list):
        if e.cognitive and "run_end" in e.cognitive:
            agg.score = e.cognitive["run_end"].get("score")
            break

    for e in entries_list:
        if not (e.cognitive and "tool_result" in e.cognitive):
            continue
        tr = e.cognitive["tool_result"]

        latency_ms = 0
        attempts: Optional[int] = None
        metrics = tr.get("metrics")
        if isinstance(metrics, dict):
            if isinstance(metrics.get("latency_ms"), int):
                latency_ms = metrics["latency_ms"]
            if isinstance(metrics.get("attempts"), int):
                attempts = metrics["attempts"]

        agg.tool_latency_ms_total += latency_ms
        name = tr.get("name") or tr.get("tool") or "unknown"
        group = str(name).split(".")[0] if isinstance(name, str) and "." in name else "unknown"
        agg.tool_latency_by_group[group] = agg.tool_latency_by_group.get(group, 0) + latency_ms

        if attempts is not None:
            agg.retry_attempts_total += max(0, attempts - 1)

        if tr.get("outcome") == "timeout":
            agg.timeouts += 1

        if tr.get("success") is True:
            continue

        ft = tr.get("failure_type") or "unknown"
        agg.failure_counts[ft] = agg.failure_counts.get(ft, 0) + 1
        agg.failure_latency_ms[ft] = agg.failure_latency_ms.get(ft, 0) + latency_ms

    if reader_outcome is not None:
        agg.outcome = reader_outcome[0]

    if agg.score is None and agg.outcome is not None:
        agg.score = {"time_s": None, "escaped": agg.outcome == "success"}

    return agg


def aggregate_task(eventlog_dir: str | Path, task_id: str) -> TaskAggregate:
    reader = EventLogReader(eventlog_dir)
    entries = reader.query(task_id=task_id)
    outcome = reader.get_outcome(task_id)
    return aggregate_entries(task_id, entries, reader_outcome=outcome)
