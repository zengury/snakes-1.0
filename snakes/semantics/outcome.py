from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, TypedDict


class OutcomeStatus(str, Enum):
    SUCCESS = "success"
    FAIL = "fail"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class FailureType(str, Enum):
    PERCEPTION = "perception"
    MANIPULATION = "manipulation"
    SYSTEM = "system"
    SAFETY = "safety"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ToolOutcome:
    """Failure-first tool result contract.

    This is the minimal contract Snakes enforces across all toolchains
    (mock tools, sdk2cli tools, diagnosis tools).

    NOTE: we keep the payload JSON-serializable and friendly to LLMs.
    """

    outcome: OutcomeStatus
    failure_type: Optional[FailureType] = None
    phenomenon: Optional[str] = None
    retryable: bool = False
    metrics: dict[str, Any] | None = None

    # Raw tool result (may contain legacy fields)
    result: Any = None

    # Optional: small structured state update for runtime to consume
    ontology_delta: dict[str, Any] | None = None


def validate_tool_outcome(obj: Any) -> tuple[bool, str]:
    """Validate a dict-like tool result adheres to ToolOutcome contract.

    We validate *minimally* to avoid over-design.
    """

    if not isinstance(obj, dict):
        return False, "tool result is not a dict"

    outcome = obj.get("outcome")
    if outcome is None:
        return False, "missing field: outcome"

    try:
        OutcomeStatus(outcome)
    except Exception:
        return False, f"invalid outcome: {outcome!r}"

    ft = obj.get("failure_type")
    if ft is not None:
        try:
            FailureType(ft)
        except Exception:
            return False, f"invalid failure_type: {ft!r}"

    retryable = obj.get("retryable")
    if retryable is not None and not isinstance(retryable, bool):
        return False, "retryable must be bool"

    metrics = obj.get("metrics")
    if metrics is not None and not isinstance(metrics, dict):
        return False, "metrics must be an object"

    phenomenon = obj.get("phenomenon")
    if phenomenon is not None and not isinstance(phenomenon, str):
        return False, "phenomenon must be str"

    return True, ""


def normalize_tool_outcome(obj: Any) -> dict[str, Any]:
    """Best-effort normalization.

    - Ensures required keys exist.
    - Does NOT attempt deep conversions; keep it simple.
    """

    if isinstance(obj, dict):
        if "outcome" not in obj:
            # Legacy convention: ok=True/False
            if obj.get("ok") is True:
                obj = {"outcome": "success", "result": obj}
            else:
                obj = {
                    "outcome": "fail",
                    "failure_type": "unknown",
                    "phenomenon": obj.get("error") if isinstance(obj.get("error"), str) else "unknown error",
                    "retryable": True,
                    "result": obj,
                }
        return obj

    # If it's not a dict, wrap it.
    return {"outcome": "success", "result": obj}
