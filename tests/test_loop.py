from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from snakes.loop import run_agent_loop
from snakes.types import (
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentTool,
    AgentToolResult,
    ContentBlock,
    FollowUpMessage,
    MemorySnapshot,
    SteeringMessage,
)
from tests.conftest import MockLLM, MockLLMResponse


def _make_tool(name: str = "test_tool", result: str = '{"ok":true}') -> AgentTool:
    async def execute(args: Dict[str, Any]) -> str:
        return result

    return AgentTool(
        name=name,
        description=f"Test tool {name}",
        input_schema={"type": "object", "properties": {}},
        execute=execute,
    )


def _make_concurrent_tool(name: str = "test_tool", result: str = '{"ok":true}') -> AgentTool:
    async def execute(args: Dict[str, Any]) -> str:
        return result

    return AgentTool(
        name=name,
        description=f"Test tool {name}",
        input_schema={"type": "object", "properties": {}},
        execute=execute,
        is_concurrency_safe=lambda _: True,
        execution_mode="parallel",
    )


def _make_config(llm: MockLLM, **kwargs: Any) -> AgentLoopConfig:
    return AgentLoopConfig(stream_fn=llm.stream, **kwargs)


def _make_context(tools: list[AgentTool] | None = None, **kwargs: Any) -> AgentContext:
    return AgentContext(
        system_prompt="You are a test robot.",
        tools=tools or [],
        **kwargs,
    )


async def _collect_events(events: List[AgentEvent], event: AgentEvent) -> None:
    events.append(event)


@pytest.mark.asyncio
async def test_simple_prompt():
    llm = MockLLM([MockLLMResponse(text="Hello from robot!")])
    config = _make_config(llm)
    ctx = _make_context()
    events: List[AgentEvent] = []
    signal = asyncio.Event()

    result = await run_agent_loop(
        ["Hi robot"], ctx, config,
        lambda e: _collect_events(events, e), signal,
    )

    event_types = [e.type for e in events]
    assert "agent_start" in event_types
    assert "agent_end" in event_types
    assert "message_start" in event_types
    assert "message_end" in event_types
    assert any(m.role == "assistant" for m in result)


@pytest.mark.asyncio
async def test_tool_execution():
    tool = _make_tool("camera_get", '{"image":"base64..."}')
    llm = MockLLM([
        MockLLMResponse(tool_calls=[{"name": "camera_get", "id": "tc1", "input": {}}]),
        MockLLMResponse(text="I see the room."),
    ])
    config = _make_config(llm)
    ctx = _make_context(tools=[tool])
    events: List[AgentEvent] = []
    signal = asyncio.Event()

    result = await run_agent_loop(
        ["What do you see?"], ctx, config,
        lambda e: _collect_events(events, e), signal,
    )

    event_types = [e.type for e in events]
    assert "tool_execution_start" in event_types
    assert "tool_execution_end" in event_types
    assert len(result) >= 3


@pytest.mark.asyncio
async def test_parallel_tool_execution():
    cam_tool = _make_concurrent_tool("camera_get", '{"image":"data"}')
    lidar_tool = _make_concurrent_tool("lidar_get", '{"scan":"points"}')
    llm = MockLLM([
        MockLLMResponse(tool_calls=[
            {"name": "camera_get", "id": "tc1", "input": {"camera_id": "front"}},
            {"name": "lidar_get", "id": "tc2", "input": {}},
        ]),
        MockLLMResponse(text="Sensors captured."),
    ])
    config = _make_config(llm, execution_mode="parallel")
    ctx = _make_context(tools=[cam_tool, lidar_tool])
    events: List[AgentEvent] = []
    signal = asyncio.Event()

    result = await run_agent_loop(
        ["Capture all sensors"], ctx, config,
        lambda e: _collect_events(events, e), signal,
    )

    event_types = [e.type for e in events]
    assert "tool_execution_start" in event_types
    assert "tool_execution_end" in event_types
    tool_result_msgs = [
        m for m in result
        if m.role == "user" and any(b.type == "tool_result" for b in m.content)
    ]
    assert len(tool_result_msgs) >= 1
    tool_result_blocks = [
        b for m in tool_result_msgs for b in m.content if b.type == "tool_result"
    ]
    assert len(tool_result_blocks) == 2


@pytest.mark.asyncio
async def test_sequential_tool_execution():
    move_tool = _make_tool("base_move", '{"moved":true}')
    grip_tool = _make_tool("arm_gripper", '{"gripped":true}')
    llm = MockLLM([
        MockLLMResponse(tool_calls=[
            {"name": "base_move", "id": "tc1", "input": {"x": 1.0}},
        ]),
        MockLLMResponse(tool_calls=[
            {"name": "arm_gripper", "id": "tc2", "input": {"action": "close"}},
        ]),
        MockLLMResponse(text="Moved and grabbed."),
    ])
    config = _make_config(llm, execution_mode="sequential")
    ctx = _make_context(tools=[move_tool, grip_tool])
    events: List[AgentEvent] = []
    signal = asyncio.Event()

    result = await run_agent_loop(
        ["Move forward then grab"], ctx, config,
        lambda e: _collect_events(events, e), signal,
    )

    tool_exec_starts = [e for e in events if e.type == "tool_execution_start"]
    assert len(tool_exec_starts) == 2
    assert any(m.role == "assistant" and m.text and "Moved" in m.text for m in result)


@pytest.mark.asyncio
async def test_steering_message():
    llm = MockLLM([
        MockLLMResponse(text="Working on it..."),
        MockLLMResponse(text="Got the steering message."),
    ])
    config = _make_config(llm)
    ctx = _make_context()
    signal = asyncio.Event()
    steering_queue: asyncio.Queue[SteeringMessage] = asyncio.Queue()
    steering_queue.put_nowait(SteeringMessage(content="Change direction!", priority=1))

    result = await run_agent_loop(
        ["Start"], ctx, config,
        lambda e: asyncio.sleep(0), signal,
        steering_queue=steering_queue,
    )

    assert any("[Steering]" in m.text for m in result if m.role == "user")


@pytest.mark.asyncio
async def test_follow_up_message():
    llm = MockLLM([
        MockLLMResponse(text="Step one done."),
        MockLLMResponse(text="Follow-up done."),
    ])
    config = _make_config(llm)
    ctx = _make_context()
    signal = asyncio.Event()
    follow_up_queue: asyncio.Queue[FollowUpMessage] = asyncio.Queue()
    follow_up_queue.put_nowait(FollowUpMessage(content="Now do step two"))

    result = await run_agent_loop(
        ["Do step one"], ctx, config,
        lambda e: asyncio.sleep(0), signal,
        follow_up_queue=follow_up_queue,
    )

    user_msgs = [m for m in result if m.role == "user"]
    assert any("step two" in m.text.lower() for m in user_msgs)
    assistant_msgs = [m for m in result if m.role == "assistant"]
    assert len(assistant_msgs) >= 2


@pytest.mark.asyncio
async def test_before_tool_call_block():
    tool = _make_tool("dangerous_tool")

    async def block_dangerous(ctx: Any) -> None:
        if ctx.tool_call.tool_name == "dangerous_tool":
            ctx.blocked = True
            ctx.block_reason = "Safety: tool blocked"

    llm = MockLLM([
        MockLLMResponse(tool_calls=[{"name": "dangerous_tool", "id": "tc1", "input": {}}]),
        MockLLMResponse(text="Tool was blocked."),
    ])
    config = _make_config(llm, before_tool_call=block_dangerous)
    ctx = _make_context(tools=[tool])
    events: List[AgentEvent] = []
    signal = asyncio.Event()

    result = await run_agent_loop(
        ["Do dangerous thing"], ctx, config,
        lambda e: _collect_events(events, e), signal,
    )

    tool_results = [m for m in result if m.role == "user" and any(
        b.type == "tool_result" and b.is_error for b in m.content
    )]
    assert len(tool_results) >= 1


@pytest.mark.asyncio
async def test_abort():
    tool = _make_tool("slow_tool")
    llm = MockLLM([
        MockLLMResponse(tool_calls=[{"name": "slow_tool", "id": "tc1", "input": {}}]),
    ])
    config = _make_config(llm)
    ctx = _make_context(tools=[tool])
    signal = asyncio.Event()
    signal.set()

    result = await run_agent_loop(
        ["Start task"], ctx, config,
        lambda e: asyncio.sleep(0), signal,
    )

    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_error_handling():
    async def failing_stream(
        system_prompt: str,
        messages: Any,
        tools: Any,
        max_tokens: int,
    ):
        raise RuntimeError("LLM service unavailable")
        yield  # noqa: E501 - make it a generator

    config = AgentLoopConfig(stream_fn=failing_stream)
    ctx = _make_context()
    events: List[AgentEvent] = []
    signal = asyncio.Event()

    with pytest.raises(RuntimeError, match="unavailable"):
        await run_agent_loop(
            ["Do something"], ctx, config,
            lambda e: _collect_events(events, e), signal,
        )
