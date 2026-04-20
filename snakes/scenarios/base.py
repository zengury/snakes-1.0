from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from snakes.types import AgentTool


@dataclass
class ScenarioRunContext:
    """Runtime-owned context for a single scenario run."""

    robot_id: str
    task_id: str
    seed: int | None = None


class Scenario(Protocol):
    """A long-horizon task environment.

    Scenarios are responsible for:
    - providing observations for the agent ("look around")
    - providing tools (actions) that may succeed or fail
    - defining termination and scoring
    - providing optional scenario-specific prompt instructions (application layer)

    Runtime is responsible for:
    - agent loop
    - event logging
    - toolchain semantics (timeout/retry)
    - autonomy safeguards
    """

    name: str

    async def reset(self, level: int, *, ctx: ScenarioRunContext) -> dict[str, Any]: ...

    async def observe(self) -> dict[str, Any]: ...

    def tools(self) -> list[AgentTool]: ...

    def is_done(self) -> bool: ...

    def score(self) -> dict[str, Any]: ...

    def prompt_instructions(self) -> str: ...
