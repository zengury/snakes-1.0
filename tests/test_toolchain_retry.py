from __future__ import annotations

import asyncio

import pytest

from snakes.loop import run_agent_loop
from snakes.types import AgentContext, AgentLoopConfig, AgentTool
from tests.conftest import MockLLM, MockLLMResponse


@pytest.mark.asyncio
async def test_tool_retry_on_system_timeout() -> None:
    calls = {"n": 0}

    async def execute(_args):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "outcome": "timeout",
                "failure_type": "system",
                "phenomenon": "sim timeout",
                "retryable": True,
            }
        return {
            "outcome": "success",
            "result": "ok",
            "metrics": {"latency_ms": 1},
        }

    tool = AgentTool(
        name="camera.get",
        description="cam",
        input_schema={"type": "object", "properties": {}},
        execute=execute,
        max_retries=1,
        timeout_s=None,
    )

    llm = MockLLM([
        MockLLMResponse(tool_calls=[{"name": "camera.get", "id": "tc1", "input": {}}]),
        MockLLMResponse(text="done"),
    ])

    cfg = AgentLoopConfig(stream_fn=llm.stream, execution_mode="sequential", max_turns=5)
    ctx = AgentContext(system_prompt="x", tools=[tool])

    await run_agent_loop(["go"], ctx, cfg, lambda e: asyncio.sleep(0), asyncio.Event())

    assert calls["n"] == 2
