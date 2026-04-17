#!/usr/bin/env python3
"""Export EventLog entries as a training dataset for VLA models.

Supports LeRobot (HuggingFace datasets), RLDS (TensorFlow Datasets), and a
custom JSON format that preserves reasoning chains.

Usage:
    python scripts/export_dataset.py --task milk_grasp --format lerobot --out ./datasets/milk_v1/
    python scripts/export_dataset.py --outcome success --since 2026-04-01 --format custom
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.eventlog import EventLogReader


def export_custom(
    reader: EventLogReader,
    out: Path,
    task_filter: str | None,
    outcome_filter: str | None,
    since: str | None,
) -> int:
    """Custom JSON format: one file per task with aligned trajectory + reasoning."""
    out.mkdir(parents=True, exist_ok=True)
    groups = reader.group_by_task(since=since)
    exported = 0
    for task_id, entries in groups.items():
        task_end = [e for e in entries if "task_end" in (e.tags or [])]
        if not task_end:
            continue
        outcome = task_end[-1].outcome
        if outcome_filter and outcome != outcome_filter:
            continue

        tags = set()
        for e in entries:
            tags.update(e.tags or [])
        if task_filter and task_filter not in tags:
            continue

        physical = [e for e in entries if e.source == "physical"]
        cognitive = [e for e in entries if e.source == "cognitive"]

        record = {
            "task_id": task_id,
            "robot_id": entries[0].robot_id,
            "outcome": outcome,
            "failure_reason": task_end[-1].failure_reason,
            "failure_phenomenon": task_end[-1].failure_phenomenon,
            "tags": sorted(tags),
            "trajectory": [
                {"ts": e.ts, "physical": e.physical} for e in physical
            ],
            "reasoning": [
                {
                    "ts": e.ts,
                    "turn": (e.cognitive or {}).get("turn"),
                    "reasoning": (e.cognitive or {}).get("reasoning"),
                    "tool_call": (e.cognitive or {}).get("tool_call"),
                    "tool_result": (e.cognitive or {}).get("tool_result"),
                }
                for e in cognitive
            ],
        }
        (out / f"{task_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
        exported += 1
    return exported


def export_lerobot(
    reader: EventLogReader,
    out: Path,
    task_filter: str | None,
    outcome_filter: str | None,
    since: str | None,
) -> int:
    """LeRobot format: Parquet files with columns [observation.state, action, reward, ...].

    This is a minimal stub — full LeRobot spec requires specific dtypes and chunking.
    See: https://github.com/huggingface/lerobot/blob/main/docs/DATASET_FORMAT.md
    """
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        print("error: pandas required for lerobot format (pip install pandas pyarrow)", file=sys.stderr)
        return 0

    out.mkdir(parents=True, exist_ok=True)
    groups = reader.group_by_task(since=since)
    exported = 0

    all_rows: list[dict[str, Any]] = []
    for task_id, entries in groups.items():
        task_end = [e for e in entries if "task_end" in (e.tags or [])]
        if not task_end:
            continue
        outcome = task_end[-1].outcome
        if outcome_filter and outcome != outcome_filter:
            continue

        tags = {t for e in entries for t in (e.tags or [])}
        if task_filter and task_filter not in tags:
            continue

        physical = [e for e in entries if e.source == "physical"]
        for idx, e in enumerate(physical):
            if not e.physical:
                continue
            joints = e.physical.get("joints", {})
            all_rows.append({
                "episode_index": task_id,
                "frame_index": idx,
                "timestamp": e.ts,
                "observation.state": joints.get("q", []),
                "observation.velocity": joints.get("dq", []),
                "observation.effort": joints.get("tau_est", []),
                "action": [],
                "next.done": idx == len(physical) - 1,
                "next.reward": 1.0 if outcome == "success" else 0.0,
                "task": ",".join(sorted(tags)),
            })
        exported += 1

    if all_rows:
        df = pd.DataFrame(all_rows)
        df.to_parquet(out / "episodes.parquet", engine="pyarrow")

    return exported


def main() -> int:
    p = argparse.ArgumentParser(description="Export EventLog as VLA training dataset")
    p.add_argument("--eventlog", default="mcp/storage/eventlog", help="EventLog root directory")
    p.add_argument("--out", required=True, help="Output directory")
    p.add_argument("--format", choices=["custom", "lerobot", "rlds"], default="custom")
    p.add_argument("--task", help="Filter by task tag (e.g. milk_grasp)")
    p.add_argument("--outcome", choices=["success", "failure", "partial"])
    p.add_argument("--since", help="ISO date, e.g. 2026-04-01")
    args = p.parse_args()

    reader = EventLogReader(args.eventlog)
    out = Path(args.out)

    if args.format == "custom":
        n = export_custom(reader, out, args.task, args.outcome, args.since)
    elif args.format == "lerobot":
        n = export_lerobot(reader, out, args.task, args.outcome, args.since)
    else:
        print(f"format {args.format} not yet implemented", file=sys.stderr)
        return 1

    print(f"exported {n} tasks to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
