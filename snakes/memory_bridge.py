from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class Memory(Protocol):
    def log_episodic(self, event: str, data: dict[str, Any]) -> None: ...
    def query_semantic(self, query: str, top_k: int = 5) -> list[dict[str, Any]]: ...
    def update_reflex(self, snapshot: dict[str, Any]) -> None: ...
    def check_reflex(self, command: str, args: dict[str, Any]) -> dict[str, Any]: ...
    def check_safety(self, command: str, args: dict[str, Any]) -> tuple[bool, str]: ...
    def run_critic(self) -> dict[str, Any]: ...


@dataclass
class MemoryBridge:
    memory: Memory
    _turn_events: list[dict[str, Any]] = field(default_factory=list, init=False)

    def on_tool_execution_start(self, tool_name: str, args: dict[str, Any]) -> None:
        event = {
            "type": "tool_start",
            "tool": tool_name,
            "args": args,
            "timestamp": time.time(),
        }
        self._turn_events.append(event)
        self.memory.log_episodic("tool_execution_start", event)

    def on_tool_execution_end(
        self, tool_name: str, args: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any] | None:
        event = {
            "type": "tool_end",
            "tool": tool_name,
            "args": args,
            "result": result,
            "timestamp": time.time(),
        }
        self._turn_events.append(event)
        self.memory.log_episodic("tool_execution_end", event)

        anomaly = self.memory.check_reflex(tool_name, result)
        if anomaly.get("anomaly"):
            return anomaly
        return None

    def on_turn_end(self, turn_number: int, summary: dict[str, Any]) -> None:
        snapshot = {
            "turn": turn_number,
            "events": list(self._turn_events),
            "summary": summary,
            "timestamp": time.time(),
        }
        self.memory.update_reflex(snapshot)
        self._turn_events.clear()

    def on_agent_end(self, final_state: dict[str, Any]) -> dict[str, Any]:
        self.memory.log_episodic("agent_end", {
            "state": final_state,
            "timestamp": time.time(),
        })
        return self.memory.run_critic()


def create_memory(robot_name: str) -> Memory:
    try:
        import memkit
    except ImportError:
        raise ImportError(
            "memkit is required for memory features. "
            "Install with: pip install snakes[memkit]"
        )

    config = memkit.Config(
        namespace=f"snakes.{robot_name}",
        episodic=memkit.EpisodicConfig(max_events=10000),
        semantic=memkit.SemanticConfig(embedding_model="default"),
        reflex=memkit.ReflexConfig(anomaly_threshold=0.8),
        safety=memkit.SafetyConfig(enabled=True),
    )
    return memkit.Memory(config)


def query_relevant_memory(memory: Memory, task_description: str) -> dict[str, Any]:
    results = memory.query_semantic(task_description, top_k=10)
    return {
        "query": task_description,
        "matches": results,
        "count": len(results),
    }


def check_safety(memory: Memory, command: str, args: dict[str, Any]) -> tuple[bool, str]:
    return memory.check_safety(command, args)
