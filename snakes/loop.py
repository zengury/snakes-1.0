from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional

from .types import (
    AfterToolCallContext,
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentTool,
    AgentToolCall,
    AgentToolResult,
    BeforeToolCallContext,
    ContentBlock,
    EmitFn,
    FollowUpMessage,
    SteeringMessage,
)


async def run_agent_loop(
    prompts: List[str],
    context: AgentContext,
    config: AgentLoopConfig,
    emit: EmitFn,
    signal: asyncio.Event,
    steering_queue: Optional[asyncio.Queue[SteeringMessage]] = None,
    follow_up_queue: Optional[asyncio.Queue[FollowUpMessage]] = None,
) -> List[AgentMessage]:
    if steering_queue is None:
        steering_queue = asyncio.Queue()
    if follow_up_queue is None:
        follow_up_queue = asyncio.Queue()

    await emit(AgentEvent(type="agent_start"))

    initial_messages: List[AgentMessage] = []
    for prompt_text in prompts:
        initial_messages.append(
            AgentMessage(
                role="user",
                content=[ContentBlock(type="text", text=prompt_text)],
            )
        )

    try:
        result = await run_loop(
            context=context,
            new_messages=initial_messages,
            config=config,
            signal=signal,
            emit=emit,
            steering_queue=steering_queue,
            follow_up_queue=follow_up_queue,
        )
    finally:
        await emit(AgentEvent(type="agent_end"))

    return result


async def run_loop(
    context: AgentContext,
    new_messages: List[AgentMessage],
    config: AgentLoopConfig,
    signal: asyncio.Event,
    emit: EmitFn,
    steering_queue: asyncio.Queue[SteeringMessage],
    follow_up_queue: asyncio.Queue[FollowUpMessage],
) -> List[AgentMessage]:
    context.messages.extend(new_messages)
    turn_count = 0

    while True:
        if signal.is_set():
            break

        if turn_count >= config.max_turns:
            break

        turn_count += 1
        await emit(AgentEvent(type="turn_start", data={"turn": turn_count}))

        assistant_message = await stream_assistant_response(
            context=context,
            config=config,
            signal=signal,
            emit=emit,
        )

        if signal.is_set():
            await emit(AgentEvent(type="turn_end", data={"turn": turn_count, "aborted": True}))
            break

        context.messages.append(assistant_message)

        tool_calls = _extract_tool_calls(assistant_message)

        if not tool_calls:
            # No tool calls -- check for steering and follow-up messages
            # before ending the loop.
            injected = await _drain_queues(
                context, steering_queue, follow_up_queue
            )
            await emit(AgentEvent(type="turn_end", data={"turn": turn_count}))
            if injected:
                continue
            break

        tool_results = await execute_tool_calls(
            context=context,
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            config=config,
            signal=signal,
            emit=emit,
        )

        if signal.is_set():
            # Produce error results for any tool calls that didn't complete
            # so the message history stays well-formed.
            remaining_ids = {tc.id for tc in tool_calls} - {
                r.tool_call_id for r in tool_results
            }
            for tc in tool_calls:
                if tc.id in remaining_ids:
                    tool_results.append(
                        AgentToolResult(
                            tool_call_id=tc.id,
                            tool_name=tc.tool_name,
                            content="Interrupted by user",
                            is_error=True,
                        )
                    )

        result_message = _build_tool_result_message(tool_results)
        context.messages.append(result_message)

        # Drain steering messages injected mid-turn
        await _drain_queues(context, steering_queue, follow_up_queue)

        await emit(AgentEvent(type="turn_end", data={"turn": turn_count}))

        if signal.is_set():
            break

    return context.messages


async def stream_assistant_response(
    context: AgentContext,
    config: AgentLoopConfig,
    signal: asyncio.Event,
    emit: EmitFn,
) -> AgentMessage:
    message_id = str(uuid.uuid4())
    accumulated_blocks: List[ContentBlock] = []
    current_text_parts: List[str] = []

    await emit(
        AgentEvent(
            type="message_start",
            message=AgentMessage(id=message_id, role="assistant"),
        )
    )

    if config.stream_fn is None:
        raise RuntimeError(
            "AgentLoopConfig.stream_fn must be set before running the agent loop"
        )

    tool_api_defs = [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in context.tools
    ]

    async for delta_text, block in config.stream_fn(
        context.system_prompt,
        context.messages,
        context.tools,
        context.max_tokens,
    ):
        if signal.is_set():
            break

        if delta_text:
            current_text_parts.append(delta_text)
            await emit(
                AgentEvent(
                    type="message_update",
                    delta=delta_text,
                    message=AgentMessage(id=message_id, role="assistant"),
                )
            )

        if block is not None:
            # Flush accumulated text into a text block before appending
            # the non-text block.
            if block.type != "text" and current_text_parts:
                accumulated_blocks.append(
                    ContentBlock(type="text", text="".join(current_text_parts))
                )
                current_text_parts.clear()

            if block.type == "text":
                pass  # text is accumulated via delta_text above
            else:
                accumulated_blocks.append(block)

    # Flush any trailing text
    if current_text_parts:
        accumulated_blocks.append(
            ContentBlock(type="text", text="".join(current_text_parts))
        )

    assistant_message = AgentMessage(
        id=message_id,
        role="assistant",
        content=accumulated_blocks,
    )

    await emit(
        AgentEvent(type="message_end", message=assistant_message)
    )

    return assistant_message


async def execute_tool_calls(
    context: AgentContext,
    assistant_message: AgentMessage,
    tool_calls: List[AgentToolCall],
    config: AgentLoopConfig,
    signal: asyncio.Event,
    emit: EmitFn,
) -> List[AgentToolResult]:
    await emit(
        AgentEvent(
            type="tool_execution_start",
            data={"tool_calls": [tc.tool_name for tc in tool_calls]},
        )
    )

    tool_map = {t.name: t for t in context.tools}
    results: List[AgentToolResult] = []

    batches = _partition_tool_calls(tool_calls, tool_map, config.execution_mode)

    for is_concurrent, batch in batches:
        if signal.is_set():
            break

        if is_concurrent and len(batch) > 1:
            batch_results = await _execute_batch_parallel(
                batch=batch,
                tool_map=tool_map,
                context=context,
                config=config,
                signal=signal,
                emit=emit,
            )
            results.extend(batch_results)
        else:
            for tc in batch:
                if signal.is_set():
                    break
                result = await _execute_single_tool_call(
                    tool_call=tc,
                    tool_map=tool_map,
                    context=context,
                    config=config,
                    signal=signal,
                    emit=emit,
                )
                results.append(result)

    await emit(
        AgentEvent(
            type="tool_execution_end",
            data={"results_count": len(results)},
        )
    )

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_tool_calls(message: AgentMessage) -> List[AgentToolCall]:
    calls: List[AgentToolCall] = []
    for block in message.content:
        if block.type == "tool_use" and block.tool_use_id and block.tool_name:
            calls.append(
                AgentToolCall(
                    id=block.tool_use_id,
                    tool_name=block.tool_name,
                    tool_input=block.tool_input or {},
                    assistant_message_id=message.id,
                )
            )
    return calls


def _partition_tool_calls(
    tool_calls: List[AgentToolCall],
    tool_map: Dict[str, AgentTool],
    default_mode: str,
) -> List[tuple[bool, List[AgentToolCall]]]:
    """Partition tool calls into batches of (is_concurrent, calls).

    Consecutive concurrency-safe calls are grouped together; everything
    else runs one at a time.  Mirrors Pi's partitionToolCalls.
    """
    batches: List[tuple[bool, List[AgentToolCall]]] = []

    for tc in tool_calls:
        tool = tool_map.get(tc.tool_name)
        is_safe = False
        if tool is not None:
            try:
                is_safe = tool.is_concurrency_safe(tc.tool_input)
            except Exception:
                is_safe = False

        if default_mode == "sequential":
            is_safe = False

        if is_safe and batches and batches[-1][0]:
            batches[-1][1].append(tc)
        else:
            batches.append((is_safe, [tc]))

    return batches


async def _execute_batch_parallel(
    batch: List[AgentToolCall],
    tool_map: Dict[str, AgentTool],
    context: AgentContext,
    config: AgentLoopConfig,
    signal: asyncio.Event,
    emit: EmitFn,
) -> List[AgentToolResult]:
    semaphore = asyncio.Semaphore(config.max_tool_concurrency)

    async def _run(tc: AgentToolCall) -> AgentToolResult:
        async with semaphore:
            return await _execute_single_tool_call(
                tc, tool_map, context, config, signal, emit
            )

    tasks = [asyncio.create_task(_run(tc)) for tc in batch]
    return list(await asyncio.gather(*tasks))


async def _execute_single_tool_call(
    tool_call: AgentToolCall,
    tool_map: Dict[str, AgentTool],
    context: AgentContext,
    config: AgentLoopConfig,
    signal: asyncio.Event,
    emit: EmitFn,
) -> AgentToolResult:
    tool = tool_map.get(tool_call.tool_name)

    if tool is None:
        return AgentToolResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.tool_name,
            content=f"Error: No such tool available: {tool_call.tool_name}",
            is_error=True,
        )

    # --- before hook (safety checks, permission gates) ---
    if config.before_tool_call is not None:
        before_ctx = BeforeToolCallContext(
            tool_call=tool_call,
            tool=tool,
            messages=context.messages,
        )
        await config.before_tool_call(before_ctx)

        if before_ctx.blocked:
            return AgentToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.tool_name,
                content=before_ctx.block_reason or "Tool call blocked by safety hook",
                is_error=True,
            )

        if before_ctx.substitute_result is not None:
            return AgentToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.tool_name,
                content=before_ctx.substitute_result,
            )

    # --- execute ---
    try:
        raw_result = await tool.execute(tool_call.tool_input)
        is_error = False
    except Exception as exc:
        raw_result = f"Error executing {tool_call.tool_name}: {exc}"
        is_error = True

    # --- observe robot state (verify step) ---
    robot_state: Optional[Dict[str, Any]] = None
    if config.observe_robot_state is not None:
        try:
            robot_state = await config.observe_robot_state()
        except Exception:
            pass

    result = AgentToolResult(
        tool_call_id=tool_call.id,
        tool_name=tool_call.tool_name,
        content=raw_result,
        is_error=is_error,
        robot_state_snapshot=robot_state,
    )

    # --- after hook (memory writes, state diff observations) ---
    if config.after_tool_call is not None:
        after_ctx = AfterToolCallContext(
            tool_call=tool_call,
            tool=tool,
            result=result,
            messages=context.messages,
        )
        await config.after_tool_call(after_ctx)

        if after_ctx.override_result is not None:
            result = AgentToolResult(
                tool_call_id=result.tool_call_id,
                tool_name=result.tool_name,
                content=after_ctx.override_result,
                is_error=result.is_error,
                robot_state_snapshot=result.robot_state_snapshot,
            )

        if after_ctx.observation is not None:
            result = AgentToolResult(
                tool_call_id=result.tool_call_id,
                tool_name=result.tool_name,
                content=result.content + "\n\n[Observation] " + after_ctx.observation,
                is_error=result.is_error,
                robot_state_snapshot=result.robot_state_snapshot,
            )

    # --- episodic memory write ---
    if config.write_episodic_memory is not None and not is_error:
        try:
            summary = (
                f"Tool {tool_call.tool_name} called with "
                f"{tool_call.tool_input!r} -> {raw_result[:200]}"
            )
            await config.write_episodic_memory(summary)
        except Exception:
            pass

    return result


def _build_tool_result_message(results: List[AgentToolResult]) -> AgentMessage:
    blocks: List[ContentBlock] = []
    for r in results:
        blocks.append(
            ContentBlock(
                type="tool_result",
                tool_use_id=r.tool_call_id,
                tool_result_content=r.content,
                is_error=r.is_error,
            )
        )
    return AgentMessage(role="user", content=blocks)


async def _drain_queues(
    context: AgentContext,
    steering_queue: asyncio.Queue[SteeringMessage],
    follow_up_queue: asyncio.Queue[FollowUpMessage],
) -> bool:
    """Drain steering and follow-up queues into context.messages.

    Returns True if any messages were injected (the loop should continue).
    """
    injected = False

    # Steering messages: injected mid-turn with priority ordering
    steering: List[SteeringMessage] = []
    while not steering_queue.empty():
        try:
            steering.append(steering_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    steering.sort(key=lambda m: m.priority, reverse=True)
    for sm in steering:
        context.messages.append(
            AgentMessage(
                role="user",
                content=[ContentBlock(type="text", text=f"[Steering] {sm.content}")],
            )
        )
        injected = True

    # Follow-up messages: queued for after the current turn
    while not follow_up_queue.empty():
        try:
            fm = follow_up_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        context.messages.append(
            AgentMessage(
                role="user",
                content=[ContentBlock(type="text", text=fm.content)],
            )
        )
        injected = True

    return injected
