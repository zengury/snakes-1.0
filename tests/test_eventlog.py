"""Tests for the unified EventLog."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from mcp.eventlog import EventLogEntry, EventLogReader, EventLogWriter


def test_write_and_read_basic() -> None:
    with tempfile.TemporaryDirectory() as d:
        writer = EventLogWriter(d, robot_id="x2-001")
        writer.bind_task("task-a")
        writer.write_cognitive({"turn": 0, "reasoning": "start"})
        writer.write_physical({"joints": {"q": [0.0, 0.1]}})
        writer.set_outcome("task-a", "success")
        writer.close()

        reader = EventLogReader(d)
        entries = reader.query(task_id="task-a")
        assert len(entries) == 3
        assert entries[0].source == "cognitive"
        assert entries[1].source == "physical"
        assert entries[2].outcome == "success"


def test_task_grouping() -> None:
    with tempfile.TemporaryDirectory() as d:
        writer = EventLogWriter(d, robot_id="x2-001")
        writer.bind_task("task-a")
        writer.write_cognitive({"turn": 0})
        writer.bind_task("task-b")
        writer.write_cognitive({"turn": 0})
        writer.close()

        reader = EventLogReader(d)
        groups = reader.group_by_task()
        assert "task-a" in groups
        assert "task-b" in groups
        assert len(groups["task-a"]) == 1


def test_outcome_filtering() -> None:
    with tempfile.TemporaryDirectory() as d:
        writer = EventLogWriter(d, robot_id="x2-001")
        writer.bind_task("ok")
        writer.set_outcome("ok", "success")
        writer.bind_task("bad")
        writer.set_outcome("bad", "failure", failure_reason="slipped")
        writer.close()

        reader = EventLogReader(d)
        good = reader.query(outcome="success")
        bad = reader.query(outcome="failure")
        assert len(good) == 1
        assert len(bad) == 1
        assert bad[0].failure_reason == "slipped"


def test_trajectory_extraction() -> None:
    with tempfile.TemporaryDirectory() as d:
        writer = EventLogWriter(d, robot_id="x2-001")
        writer.bind_task("t1")
        writer.write_physical({"joints": {"q": [0.0, 0.1, 0.2]}})
        writer.write_physical({"joints": {"q": [0.1, 0.2, 0.3]}})
        writer.write_physical({"joints": {"q": [0.2, 0.3, 0.4]}})
        writer.close()

        reader = EventLogReader(d)
        traj = reader.get_trajectory("t1", field="joints.q")
        assert len(traj) == 3
        assert traj[0] == [0.0, 0.1, 0.2]
        assert traj[-1] == [0.2, 0.3, 0.4]


def test_reasoning_chain() -> None:
    with tempfile.TemporaryDirectory() as d:
        writer = EventLogWriter(d, robot_id="x2-001")
        writer.bind_task("t1")
        writer.write_cognitive({"reasoning": "walk to aisle"})
        writer.write_cognitive({"reasoning": "approach shelf"})
        writer.write_cognitive({"reasoning": "grasp item"})
        writer.close()

        reader = EventLogReader(d)
        chain = reader.get_reasoning_chain("t1")
        assert chain == ["walk to aisle", "approach shelf", "grasp item"]


def test_jsonl_roundtrip() -> None:
    entry = EventLogEntry(
        ts="2026-04-17T10:30:00.123Z",
        seq=1,
        session_id="s1",
        robot_id="g1-01",
        task_id="t-abc",
        source="cognitive",
        tags=["grasp"],
        cognitive={"turn": 1, "reasoning": "test"},
    )
    line = entry.to_jsonl()
    parsed = json.loads(line)
    assert parsed["task_id"] == "t-abc"
    restored = EventLogEntry.from_jsonl(line)
    assert restored.robot_id == "g1-01"
    assert restored.cognitive == {"turn": 1, "reasoning": "test"}


def test_writer_context_manager() -> None:
    with tempfile.TemporaryDirectory() as d:
        with EventLogWriter(d, robot_id="x2-001") as writer:
            writer.bind_task("t1")
            writer.write_cognitive({"turn": 0})
        assert (Path(d)).exists()


def test_tag_filter() -> None:
    with tempfile.TemporaryDirectory() as d:
        writer = EventLogWriter(d, robot_id="x2-001")
        writer.write_cognitive({"turn": 0}, tags=["grasp", "milk"])
        writer.write_cognitive({"turn": 1}, tags=["walk"])
        writer.write_cognitive({"turn": 2}, tags=["grasp", "cup"])
        writer.close()

        reader = EventLogReader(d)
        grasps = reader.query(tags=["grasp"])
        assert len(grasps) == 2
