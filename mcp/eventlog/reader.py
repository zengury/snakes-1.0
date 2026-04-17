"""EventLog reader — queries across rotated JSONL files."""
from __future__ import annotations

import gzip
import io
from pathlib import Path
from typing import Any, Iterator, Optional

from mcp.eventlog.schema import EventLogEntry, Outcome, Source


class EventLogReader:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _files(self, since: Optional[str] = None, until: Optional[str] = None) -> list[Path]:
        plain = sorted(self.root.glob("*.jsonl"))
        gzd = sorted(self.root.glob("*.jsonl.gz"))
        files = plain + gzd
        if since:
            files = [f for f in files if f.stem.replace(".jsonl", "") >= since[:10]]
        if until:
            files = [f for f in files if f.stem.replace(".jsonl", "") <= until[:10]]
        return files

    def _iter_file(self, path: Path) -> Iterator[EventLogEntry]:
        if path.suffix == ".gz":
            fp: Any = gzip.open(path, "rt", encoding="utf-8")
        else:
            fp = open(path, "r", encoding="utf-8")
        with fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield EventLogEntry.from_jsonl(line)
                except (ValueError, TypeError):
                    continue

    def query(
        self,
        task_id: Optional[str] = None,
        robot_id: Optional[str] = None,
        source: Optional[Source] = None,
        outcome: Optional[Outcome] = None,
        tags: Optional[list[str]] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[EventLogEntry]:
        results: list[EventLogEntry] = []
        tag_set = set(tags) if tags else None
        for f in self._files(since=since, until=until):
            for e in self._iter_file(f):
                if task_id and e.task_id != task_id:
                    continue
                if robot_id and e.robot_id != robot_id:
                    continue
                if source and e.source != source:
                    continue
                if outcome and e.outcome != outcome:
                    continue
                if tag_set and not tag_set.issubset(set(e.tags or [])):
                    continue
                if since and e.ts < since:
                    continue
                if until and e.ts > until:
                    continue
                results.append(e)
                if limit and len(results) >= limit:
                    return results
        return results

    def group_by_task(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> dict[str, list[EventLogEntry]]:
        groups: dict[str, list[EventLogEntry]] = {}
        for f in self._files(since=since, until=until):
            for e in self._iter_file(f):
                if not e.task_id:
                    continue
                groups.setdefault(e.task_id, []).append(e)
        return groups

    def get_trajectory(
        self,
        task_id: str,
        field: str = "joints.q",
    ) -> list[list[float]]:
        """Extract physical trajectory for a task. field is dotted path into physical dict."""
        entries = self.query(task_id=task_id, source="physical")
        path = field.split(".")
        traj: list[list[float]] = []
        for e in entries:
            if not e.physical:
                continue
            v: Any = e.physical
            try:
                for p in path:
                    v = v[p]
                traj.append(v)
            except (KeyError, TypeError):
                continue
        return traj

    def get_reasoning_chain(self, task_id: str) -> list[str]:
        entries = self.query(task_id=task_id, source="cognitive")
        chain: list[str] = []
        for e in entries:
            if e.cognitive and "reasoning" in e.cognitive:
                chain.append(e.cognitive["reasoning"])
        return chain

    def get_outcome(self, task_id: str) -> Optional[tuple[Outcome, Optional[str]]]:
        entries = self.query(task_id=task_id, tags=["task_end"])
        if not entries:
            return None
        e = entries[-1]
        if e.outcome:
            return (e.outcome, e.failure_reason)
        return None
