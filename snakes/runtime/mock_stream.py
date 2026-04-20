from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Optional

from snakes.types import AgentMessage, AgentTool, ContentBlock


@dataclass
class MockPolicyConfig:
    """A deterministic policy used for offline testing.

    This is NOT meant to be smart; it's meant to keep the golden path
    runnable without external API keys.
    """

    level: int = 1


def _iter_tool_use(messages: list[AgentMessage]):
    for m in messages:
        for b in m.content:
            if b.type == "tool_use" and b.tool_name:
                yield b.tool_name, (b.tool_input or {})


def _iter_tool_result(messages: list[AgentMessage]):
    for m in messages:
        if m.role != "user":
            continue
        for b in m.content:
            if b.type != "tool_result":
                continue
            c = b.tool_result_content
            if isinstance(c, dict):
                yield c
            elif isinstance(c, str):
                try:
                    yield json.loads(c)
                except Exception:
                    continue


def _has_called(messages: list[AgentMessage], name: str) -> bool:
    return any(tn == name for tn, _ in _iter_tool_use(messages))


def _last_result_for(
    messages: list[AgentMessage],
    tool_name: str,
    *,
    match_args: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    for tr in reversed(list(_iter_tool_result(messages))):
        if not (tr.get("tool") == tool_name or tr.get("name") == tool_name):
            continue
        if match_args:
            args = tr.get("args")
            if not isinstance(args, dict):
                continue
            ok = True
            for k, v in match_args.items():
                if args.get(k) != v:
                    ok = False
                    break
            if not ok:
                continue
        return tr
    return None


def _has_succeeded(
    messages: list[AgentMessage],
    tool_name: str,
    *,
    match_args: dict[str, Any] | None = None,
) -> bool:
    tr = _last_result_for(messages, tool_name, match_args=match_args)
    if not tr:
        return False
    return tr.get("outcome") == "success" or tr.get("success") is True


def make_mock_stream_fn(cfg: MockPolicyConfig) -> Any:
    async def _stream(
        system_prompt: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        max_tokens: int,
    ) -> AsyncGenerator[tuple[str, Optional[ContentBlock]], None]:
        # Extremely small deterministic policy for offline tests.
        # It assumes EscapeRoomMockScenario tool names.

        def tool(name: str, tool_input: dict[str, Any]) -> ContentBlock:
            return ContentBlock(
                type="tool_use",
                tool_use_id=f"mock_{name}",
                tool_name=name,
                tool_input=tool_input,
            )

        if cfg.level == 2:
            # Step 0: camera.get (retry until success)
            if not _has_succeeded(messages, "camera.get"):
                yield "", tool("camera.get", {})
                return

            # Step 1: interact table (retry until success)
            if not _has_succeeded(messages, "arm.interact", match_args={"target": "table"}):
                yield "", tool("arm.interact", {"target": "table"})
                return

            # Step 2: interact blue cup (retry until success)
            if not _has_succeeded(messages, "arm.interact", match_args={"target": "blue_cup"}):
                yield "", tool("arm.interact", {"target": "blue_cup"})
                return

            # Step 3: grab key (retry until success)
            if not _has_succeeded(messages, "arm.grab", match_args={"target": "brass_key"}):
                yield "", tool("arm.grab", {"target": "brass_key", "side": "right"})
                return

            # Step 4: use key (retry until success)
            if not _has_succeeded(messages, "arm.use"):
                yield "", tool("arm.use", {"item": "brass_key", "puzzle_index": 0})
                return

            yield "Solved.", None
            return

        if cfg.level == 3:
            # Minimal deterministic solve for the built-in mock level 3.
            # 1) cell: reveal nail, solve puzzle, go corridor
            if not _has_succeeded(messages, "camera.get"):
                yield "", tool("camera.get", {})
                return

            if not _has_succeeded(messages, "arm.interact", match_args={"target": "bed"}):
                yield "", tool("arm.interact", {"target": "bed"})
                return

            if not _has_succeeded(messages, "arm.grab", match_args={"target": "rusty_nail"}):
                yield "", tool("arm.grab", {"target": "rusty_nail", "side": "right"})
                return

            if not _has_succeeded(messages, "arm.use", match_args={"item": "rusty_nail", "puzzle_index": 0}):
                yield "", tool("arm.use", {"item": "rusty_nail", "puzzle_index": 0})
                return

            if not _has_succeeded(messages, "walk.to", match_args={"direction": "north", "_phase": "cell_to_corridor"}):
                yield "", tool("walk.to", {"direction": "north", "_phase": "cell_to_corridor"})
                return

            # 2) corridor -> lab, solve 314
            if not _has_succeeded(messages, "walk.to", match_args={"direction": "east", "_phase": "corridor_to_lab"}):
                yield "", tool("walk.to", {"direction": "east", "_phase": "corridor_to_lab"})
                return

            if not _has_succeeded(messages, "arm.use", match_args={"item": "314", "puzzle_index": 0}):
                yield "", tool("arm.use", {"item": "314", "puzzle_index": 0})
                return

            if not _has_succeeded(messages, "walk.to", match_args={"direction": "west", "_phase": "lab_to_corridor"}):
                yield "", tool("walk.to", {"direction": "west", "_phase": "lab_to_corridor"})
                return

            # 3) corridor -> control_room, solve helix, go exit
            if not _has_succeeded(messages, "walk.to", match_args={"direction": "west", "_phase": "corridor_to_control"}):
                yield "", tool("walk.to", {"direction": "west", "_phase": "corridor_to_control"})
                return

            if not _has_succeeded(messages, "arm.use", match_args={"item": "helix", "puzzle_index": 0}):
                yield "", tool("arm.use", {"item": "helix", "puzzle_index": 0})
                return

            if not _has_succeeded(messages, "walk.to", match_args={"direction": "north", "_phase": "control_to_exit"}):
                yield "", tool("walk.to", {"direction": "north", "_phase": "control_to_exit"})
                return

            yield "Escaped.", None
            return

        # Level 1: naive exploration
        if not _has_called(messages, "head.scan"):
            yield "", tool("head.scan", {})
            return

        walks = [inp.get("direction") for tn, inp in _iter_tool_use(messages) if tn == "walk.to"]
        for d in ("north", "east", "south", "west"):
            if d not in walks:
                yield "", tool("walk.to", {"direction": d})
                return

        yield "Explored.", None

    return _stream
