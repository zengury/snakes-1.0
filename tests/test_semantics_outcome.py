from __future__ import annotations

from snakes.semantics.outcome import normalize_tool_outcome, validate_tool_outcome


def test_validate_ok() -> None:
    obj = {
        "outcome": "success",
        "failure_type": None,
        "phenomenon": None,
        "retryable": False,
        "metrics": {"latency_ms": 10},
        "result": {"ok": True},
    }
    ok, reason = validate_tool_outcome(obj)
    assert ok, reason


def test_normalize_legacy_ok() -> None:
    obj = {"ok": True, "result": "x"}
    norm = normalize_tool_outcome(obj)
    ok, reason = validate_tool_outcome(norm)
    assert ok, reason
    assert norm["outcome"] == "success"


def test_normalize_legacy_error() -> None:
    obj = {"ok": False, "error": "boom"}
    norm = normalize_tool_outcome(obj)
    ok, reason = validate_tool_outcome(norm)
    assert ok, reason
    assert norm["outcome"] == "fail"
