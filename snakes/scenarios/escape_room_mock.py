from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from apps.hackathon.escape_room import EscapeRoom, create_level
from apps.hackathon.x2_mock import X2HackathonMock
from snakes.types import AgentTool

from .base import ScenarioRunContext
from .failure_injection import FailureInjectionConfig, FailureInjector


def _now_us() -> int:
    return int(time.time() * 1_000_000)


@dataclass
class EscapeRoomMockScenario:
    """Escape room scenario backed by the in-repo mock environment.

    Provides tools with Failure-First structured outcomes. The tool output
    is returned as JSON to the model, while the runtime can also log the
    structured dict to EventLog.
    """

    name: str = "escape-room"

    level: int = 1
    ctx: ScenarioRunContext | None = None

    failure_cfg: FailureInjectionConfig = FailureInjectionConfig()

    _room: EscapeRoom | None = None
    _robot: X2HackathonMock | None = None
    _injector: FailureInjector | None = None

    _sim_time_s: float = 0.0
    _start_monotonic: float = 0.0

    async def reset(self, level: int, *, ctx: ScenarioRunContext) -> dict[str, Any]:
        self.level = level
        self.ctx = ctx
        self._room = create_level(level)
        self._robot = X2HackathonMock(escape_room=self._room)
        # If user passed a seed via ScenarioRunContext, prefer it
        if ctx.seed is not None and self.failure_cfg.seed is None:
            self.failure_cfg.seed = ctx.seed
        self._injector = FailureInjector(self.failure_cfg)
        self._sim_time_s = 0.0
        self._start_monotonic = time.monotonic()
        return await self.observe()

    async def observe(self) -> dict[str, Any]:
        assert self._room is not None
        # Observation is what the verifier sees. Keep it structured.
        room = self._room.get_current_room()
        return {
            "room": room.name,
            "visible_objects": [o.name for o in room.visible_objects()],
            "exits": list(room.exits.keys()),
            "inventory": [o.name for o in self._room.inventory],
            "moves": self._room.moves,
            "hints_used": self._room.hints_used,
            "escaped": self._room.escaped,
            "level": self._room.level,
        }

    def is_done(self) -> bool:
        return bool(self._room and self._room.escaped)

    def score(self) -> dict[str, Any]:
        wall_time = max(0.0, time.monotonic() - self._start_monotonic)
        moves = self._room.moves if self._room else 0
        # V1/V2 scoring preference: time first. We expose both wall_time
        # and simulated time for deterministic analysis.
        return {
            "scenario": self.name,
            "level": self.level,
            "escaped": self.is_done(),
            "time_s": wall_time,
            "sim_time_s": self._sim_time_s,
            "moves": moves,
            "hints_used": self._room.hints_used if self._room else 0,
        }

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def prompt_instructions(self) -> str:
        # Application-layer prompt, specific to escape-room.
        # Keep it short; runtime kernel should not hardcode this.
        return (
            "You are solving an escape room. Goal: escape as fast as possible. "
            "Use tools; after each action, verify via observation. "
            "If a tool fails, recover (re-observe, then retry or choose a safer action)."
        )

    def tools(self) -> list[AgentTool]:
        assert self._robot is not None, "Scenario not reset()"

        async def call(cmd: str, args: dict[str, Any]) -> dict[str, Any]:
            assert self._robot is not None
            assert self._injector is not None

            # System failures apply to all tools
            sys_fail = self._injector.maybe_system_failure()
            if sys_fail is not None:
                return {
                    **sys_fail,
                    "tool": cmd,
                    "args": args,
                    "ts_us": _now_us(),
                }

            # Vision failures (camera)
            if cmd == "camera.get":
                vis_fail = self._injector.maybe_vision_failure()
                if vis_fail is not None:
                    return {
                        **vis_fail,
                        "tool": cmd,
                        "args": args,
                        "ts_us": _now_us(),
                    }

            # Manipulation failures (arm.*)
            if cmd.startswith("arm.") and cmd in {"arm.grab", "arm.interact", "arm.use"}:
                m_fail = self._injector.maybe_manip_failure()
                if m_fail is not None:
                    return {
                        **m_fail,
                        "tool": cmd,
                        "args": args,
                        "ts_us": _now_us(),
                    }

            # Execute underlying mock
            raw = self._robot.execute(cmd, args)

            # Update escape status after state-changing actions.
            if self._room is not None and cmd in {"walk.to", "walk.forward", "arm.use", "arm.grab", "arm.interact", "head.look", "head.scan"}:
                try:
                    self._room.check_escape()
                except Exception:
                    pass

            # Normalize to Failure-First envelope (ToolOutcome contract)
            if raw.get("ok") is True:
                outcome = {
                    "outcome": "success",
                    "failure_type": None,
                    "phenomenon": None,
                    "retryable": False,
                }
            else:
                err = raw.get("error", "unknown error")
                ft = "unknown"
                if isinstance(err, str) and err.lower().startswith("cannot see"):
                    ft = "perception"
                outcome = {
                    "outcome": "fail",
                    "failure_type": ft,
                    "phenomenon": err,
                    "retryable": True,
                }

            # Simulated time: each tool call costs some latency. This lets
            # us score deterministically even in mock.
            latency_ms = 120
            if cmd.startswith("camera"):
                latency_ms = 250
            elif cmd.startswith("walk"):
                latency_ms = 800
            elif cmd.startswith("arm"):
                latency_ms = 600
            self._sim_time_s += latency_ms / 1000.0

            return {
                **outcome,
                "tool": cmd,
                "args": args,
                "result": raw,
                "metrics": {"latency_ms": latency_ms},
                "ts_us": _now_us(),
            }

        def tool(name: str, description: str, schema: dict[str, Any]) -> AgentTool:
            async def _execute(params: dict[str, Any]) -> Any:
                # Always return structured dict; LLM adapter will stringify.
                return await call(name, params)

            # Read-only tools can be concurrent.
            is_ro = name in {"camera.get", "lidar.get", "status."}
            return AgentTool(
                name=name,
                description=description,
                input_schema=schema,
                execute=_execute,
                # Basic toolchain semantics for mainline:
                # - read tools can timeout
                # - system failures are retryable and should be retried once
                timeout_s=2.0 if is_ro else 5.0,
                max_retries=1,
                group=name.split(".")[0] if "." in name else name,
                is_concurrency_safe=(lambda _in, _ro=is_ro: _ro),
            )

        return [
            tool(
                "camera.get",
                "Get a camera observation of the current room.",
                {"type": "object", "properties": {}},
            ),
            tool(
                "lidar.get",
                "Get a lidar-like obstacle scan.",
                {"type": "object", "properties": {}},
            ),
            tool(
                "head.look",
                "Look at a specific object or scan the room.",
                {
                    "type": "object",
                    "properties": {"target": {"type": "string"}},
                },
            ),
            tool(
                "walk.to",
                "Walk to an exit direction (north/south/east/west).",
                {
                    "type": "object",
                    "properties": {"direction": {"type": "string"}},
                    "required": ["direction"],
                },
            ),
            tool(
                "arm.interact",
                "Interact with an object (may reveal hidden items).",
                {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "side": {"type": "string", "description": "left|right"},
                    },
                    "required": ["target"],
                },
            ),
            tool(
                "arm.grab",
                "Pick up an object and hold it.",
                {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "side": {"type": "string", "description": "left|right"},
                    },
                    "required": ["target"],
                },
            ),
            tool(
                "arm.use",
                "Use a held item to solve a puzzle.",
                {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string"},
                        "puzzle_index": {"type": "integer"},
                    },
                },
            ),
            tool(
                "status.",
                "Get current scenario/robot status.",
                {"type": "object", "properties": {}},
            ),
        ]
