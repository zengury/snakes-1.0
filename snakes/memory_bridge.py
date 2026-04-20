"""Bridge between agent loop events and EventLog + memkit.

The agent loop emits events. This bridge:
1. Writes them to EventLog (unified JSONL stream)
2. Optionally delegates to memkit for learning (critic pipeline)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

from eventlog.schema import EventLogEntry
from eventlog.writer import EventLogWriter


class LearningBackend(Protocol):
    """Optional memkit-compatible learning backend."""
    def query_semantic(self, query: str, top_k: int = 5) -> list[dict[str, Any]]: ...
    def check_safety(self, command: str, args: dict[str, Any]) -> tuple[bool, str]: ...
    def run_critic(self, task_events: list[dict[str, Any]]) -> dict[str, Any]: ...


@dataclass
class MemoryBridge:
    eventlog: EventLogWriter
    learner: Optional[LearningBackend] = None
    _task_events: list[dict[str, Any]] = field(default_factory=list, init=False)

    def bind_task(self, task_id: str) -> None:
        self.eventlog.bind_task(task_id)

    def unbind_task(self) -> None:
        self.eventlog.unbind_task()

    def on_tool_execution_start(self, tool_name: str, args: dict[str, Any]) -> None:
        event = {"tool": tool_name, "args": args, "phase": "start"}
        self._task_events.append(event)
        self.eventlog.write_cognitive(
            {"tool_call": {"name": tool_name, "arguments": args}},
            tags=[tool_name.split(".")[0]],
        )

    def on_tool_execution_end(
        self, tool_name: str, args: dict[str, Any], result: dict[str, Any],
        success: bool = True,
    ) -> None:
        event = {"tool": tool_name, "args": args, "result": result,
                 "success": success, "phase": "end"}
        self._task_events.append(event)
        # Store full ToolOutcome dict in EventLog for scoring/watch.
        # Keep a stable top-level shape under tool_result.
        tool_result = {
            "name": tool_name,
            "success": success,
            # ToolOutcome contract fields
            "outcome": result.get("outcome"),
            "failure_type": result.get("failure_type"),
            "phenomenon": result.get("phenomenon"),
            "retryable": result.get("retryable"),
            "metrics": result.get("metrics"),
            # Execution context
            "tool": result.get("tool", tool_name),
            "args": result.get("args", args),
            # Raw underlying result
            "result": result.get("result", result),
        }
        self.eventlog.write_cognitive(
            {"tool_result": tool_result},
            tags=[tool_name.split(".")[0]],
        )

    def on_reasoning(self, turn: int, reasoning: str) -> None:
        self.eventlog.write_cognitive(
            {"turn": turn, "reasoning": reasoning},
        )

    def on_turn_end(self, turn_number: int) -> None:
        self.eventlog.write_cognitive(
            {"turn_end": turn_number},
            tags=["turn_end"],
        )

    def on_agent_end(self, task_id: str, success: bool,
                     failure_reason: Optional[str] = None,
                     failure_phenomenon: Optional[str] = None) -> dict[str, Any]:
        outcome = "success" if success else "failure"
        self.eventlog.set_outcome(
            task_id, outcome,
            failure_reason=failure_reason,
            failure_phenomenon=failure_phenomenon,
        )
        self.eventlog.flush()

        critic_result: dict[str, Any] = {}
        if self.learner:
            critic_result = self.learner.run_critic(self._task_events)

        self._task_events.clear()
        return critic_result

    def check_safety(self, command: str, args: dict[str, Any]) -> tuple[bool, str]:
        if self.learner:
            return self.learner.check_safety(command, args)
        return True, ""

    def query_relevant(self, task_description: str) -> list[dict[str, Any]]:
        if self.learner:
            return self.learner.query_semantic(task_description)
        return []


def create_memory_bridge(
    robot_id: str,
    eventlog_dir: str | Path = "eventlog/data",
    learner: Optional[LearningBackend] = None,
) -> MemoryBridge:
    writer = EventLogWriter(eventlog_dir, robot_id=robot_id)
    return MemoryBridge(eventlog=writer, learner=learner)
