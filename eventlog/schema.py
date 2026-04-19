"""EventLog entry schema and serialization."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

Source = Literal["physical", "cognitive", "safety", "command"]
Severity = Literal["info", "warn", "critical"]
Outcome = Literal["success", "failure", "partial"]


@dataclass
class EventLogEntry:
    ts: str
    seq: int
    session_id: str
    robot_id: str

    task_id: Optional[str] = None
    source: Source = "cognitive"
    severity: Severity = "info"
    tags: list[str] = field(default_factory=list)

    physical: Optional[dict[str, Any]] = None
    cognitive: Optional[dict[str, Any]] = None
    safety: Optional[dict[str, Any]] = None
    command: Optional[dict[str, Any]] = None

    outcome: Optional[Outcome] = None
    failure_reason: Optional[str] = None
    failure_phenomenon: Optional[str] = None

    trace_id: Optional[str] = None
    user: Optional[str] = None
    latency_us: Optional[int] = None

    @staticmethod
    def now_ts() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def to_jsonl(self) -> str:
        d = {k: v for k, v in asdict(self).items() if v is not None and v != []}
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_jsonl(cls, line: str) -> "EventLogEntry":
        d = json.loads(line)
        return cls(**d)
