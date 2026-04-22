from __future__ import annotations

import tempfile

from eventlog import EventLogWriter
from snakes.runtime.score import aggregate_task


def test_aggregate_task_counts_failures_timeouts_and_retries() -> None:
    with tempfile.TemporaryDirectory() as d:
        w = EventLogWriter(d, robot_id="r1")
        w.bind_task("t1")
        w.write_cognitive({"tool_result": {
            "name": "camera.get",
            "success": False,
            "outcome": "timeout",
            "failure_type": "system",
            "phenomenon": "timeout",
            "retryable": True,
            "metrics": {"attempts": 2, "latency_ms": 200},
            "tool": "camera.get",
            "args": {},
            "result": {},
        }})
        w.write_cognitive({"tool_result": {
            "name": "arm.grab",
            "success": False,
            "outcome": "fail",
            "failure_type": "manipulation",
            "phenomenon": "slip",
            "retryable": True,
            "metrics": {"attempts": 1, "latency_ms": 600},
            "tool": "arm.grab",
            "args": {"target": "key"},
            "result": {},
        }})
        w.write_cognitive({"tool_result": {
            "name": "camera.get",
            "success": True,
            "outcome": "success",
            "failure_type": None,
            "phenomenon": None,
            "retryable": False,
            "metrics": {"attempts": 1, "latency_ms": 250},
            "tool": "camera.get",
            "args": {},
            "result": {},
        }})
        w.write_cognitive({"run_end": {
            "task_id": "t1",
            "outcome": "failure",
            "score": {"escaped": False, "time_s": 1.23},
        }})
        w.set_outcome("t1", "failure")
        w.close()

        agg = aggregate_task(d, "t1")

        assert agg.task_id == "t1"
        assert agg.outcome == "failure"
        assert agg.timeouts == 1
        assert agg.retry_attempts_total == 1
        assert agg.failure_counts == {"system": 1, "manipulation": 1}
        assert agg.tool_latency_ms_total == 200 + 600 + 250
        assert agg.tool_latency_by_group == {"camera": 450, "arm": 600}
        assert agg.score == {"escaped": False, "time_s": 1.23}
        assert agg.events >= 4


def test_aggregate_task_empty_dir_returns_zero() -> None:
    with tempfile.TemporaryDirectory() as d:
        agg = aggregate_task(d, "missing")
        assert agg.events == 0
        assert agg.timeouts == 0
        assert agg.failure_counts == {}
        assert agg.tool_latency_by_group == {}
