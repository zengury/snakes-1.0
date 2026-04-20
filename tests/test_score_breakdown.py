from __future__ import annotations

import tempfile

from eventlog import EventLogWriter
from snakes.cli import cmd_score


def test_score_includes_timeouts_and_retry_counts(monkeypatch) -> None:
    # Build a small eventlog with tool_results containing metrics.attempts
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
            "name": "camera.get",
            "success": True,
            "outcome": "success",
            "failure_type": None,
            "phenomenon": None,
            "retryable": False,
            "metrics": {"attempts": 1, "latency_ms": 200},
            "tool": "camera.get",
            "args": {},
            "result": {},
        }})
        w.set_outcome("t1", "failure")
        w.close()

        out = {}
        def fake_print(s):
            out["text"] = s

        monkeypatch.setattr("builtins.print", lambda *a, **k: fake_print(a[0] if a else ""))

        class Args:
            eventlog_dir = d
            task_id = "t1"

        cmd_score(Args())
        assert "timeouts" in out["text"]
        assert "retry_attempts_total" in out["text"]
        assert "tool_latency_ms_total" in out["text"]
        assert "tool_latency_by_group" in out["text"]
