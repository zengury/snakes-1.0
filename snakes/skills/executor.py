from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from snakes.semantics.outcome import normalize_tool_outcome
from snakes.types import AgentTool

from .skillpack import SkillPack, SkillSpec


@dataclass
class SkillRunResult:
    name: str
    ok: bool
    outcome: dict[str, Any]
    steps_executed: int


class SkillNotFound(KeyError):
    pass


class SkillExecutor:
    """Minimal skill executor (B2).

    Executes a SkillSpec by calling underlying AgentTools sequentially.

    Notes:
    - This runs inside a tool call (skill.run), so we must do our own
      timeout/retry handling and logging.
    - Keep semantics minimal: only system retries are automatic.
    """

    def __init__(
        self,
        packs: list[SkillPack],
        *,
        tool_map: dict[str, AgentTool],
        on_step_start: Optional[callable] = None,
        on_step_end: Optional[callable] = None,
    ) -> None:
        self._skills: dict[str, SkillSpec] = {}
        for p in packs:
            for s in p.skills:
                self._skills[s.name] = s

        # Underlying tools (exclude skill.run to avoid recursion)
        self._tool_map = {k: v for k, v in tool_map.items() if k != "skill.run"}

        self._on_step_start = on_step_start
        self._on_step_end = on_step_end

    def has(self, name: str) -> bool:
        return name in self._skills

    def list(self) -> list[str]:
        return sorted(self._skills.keys())

    async def run(self, name: str) -> SkillRunResult:
        spec = self._skills.get(name)
        if spec is None:
            raise SkillNotFound(name)

        last_outcome: dict[str, Any] = {
            "outcome": "success",
            "result": None,
            "metrics": {"steps": 0},
        }

        executed = 0
        for step in spec.steps:
            tool = self._tool_map.get(step.tool)
            if tool is None:
                last_outcome = {
                    "outcome": "fail",
                    "failure_type": "system",
                    "phenomenon": f"skill step tool not available: {step.tool}",
                    "retryable": False,
                    "result": None,
                    "metrics": {"steps": executed},
                }
                break

            if self._on_step_start:
                try:
                    self._on_step_start(step.tool, step.args, skill=name)
                except Exception:
                    pass

            step_outcome = await self._execute_with_semantics(tool, step.args)
            executed += 1

            if self._on_step_end:
                try:
                    self._on_step_end(step.tool, step.args, step_outcome, skill=name)
                except Exception:
                    pass

            last_outcome = step_outcome

            if last_outcome.get("outcome") != "success":
                # Stop skill on first failure.
                break

        ok = last_outcome.get("outcome") == "success"

        # Wrap as a ToolOutcome-like dict for the skill itself.
        combined = {
            "outcome": "success" if ok else (last_outcome.get("outcome") or "fail"),
            "failure_type": last_outcome.get("failure_type"),
            "phenomenon": last_outcome.get("phenomenon"),
            "retryable": False,
            "metrics": {
                "steps_executed": executed,
            },
            "result": {
                "skill": name,
                "ok": ok,
                "last": last_outcome,
            },
        }

        return SkillRunResult(name=name, ok=ok, outcome=combined, steps_executed=executed)

    async def _execute_with_semantics(self, tool: AgentTool, args: dict[str, Any]) -> dict[str, Any]:
        attempts = 0
        retry_history: list[dict[str, Any]] = []

        while True:
            attempts += 1
            try:
                if tool.timeout_s is not None:
                    raw = await asyncio.wait_for(tool.execute(args), timeout=tool.timeout_s)
                else:
                    raw = await tool.execute(args)
            except asyncio.TimeoutError:
                raw = {
                    "outcome": "timeout",
                    "failure_type": "system",
                    "phenomenon": f"tool execution timed out after {tool.timeout_s}s",
                    "retryable": True,
                    "metrics": {"attempts": attempts},
                }
            except Exception as exc:
                raw = {
                    "outcome": "fail",
                    "failure_type": "system",
                    "phenomenon": f"exception: {exc}",
                    "retryable": True,
                    "metrics": {"attempts": attempts},
                }

            norm = normalize_tool_outcome(raw)
            outcome = norm.get("outcome")
            ft = norm.get("failure_type")
            retryable = bool(norm.get("retryable"))

            if attempts <= tool.max_retries and retryable and ft == "system" and outcome in {"timeout", "fail", "partial"}:
                retry_history.append({
                    "attempt": attempts,
                    "outcome": outcome,
                    "failure_type": ft,
                    "phenomenon": norm.get("phenomenon"),
                })
                continue

            # Attach retry metadata
            norm.setdefault("metrics", {})
            if isinstance(norm["metrics"], dict):
                norm["metrics"].setdefault("attempts", attempts)
            norm.setdefault("retry_history", retry_history)
            return norm
