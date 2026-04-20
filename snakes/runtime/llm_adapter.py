from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Optional

from snakes.llm_client import LLMClient, StreamEventType
from snakes.types import AgentMessage, AgentTool, ContentBlock


def _tool_schemas(tools: list[AgentTool]) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]


def _block_to_anthropic(block: ContentBlock) -> dict[str, Any]:
    if block.type == "text":
        return {"type": "text", "text": block.text or ""}
    if block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.tool_use_id or "",
            "name": block.tool_name or "",
            "input": block.tool_input or {},
        }
    if block.type == "tool_result":
        content = block.tool_result_content
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        d: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id or "",
            "content": content,
        }
        if block.is_error:
            d["is_error"] = True
        return d
    # thinking blocks are not sent
    return {"type": "text", "text": ""}


def _messages_to_anthropic(messages: list[AgentMessage]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for m in messages:
        if m.role not in ("user", "assistant"):
            continue
        content = [_block_to_anthropic(b) for b in m.content]
        result.append({"role": m.role, "content": content})
    return result


def make_stream_fn(
    client: LLMClient,
) -> Any:
    """Build AgentLoopConfig.stream_fn from LLMClient.

    The returned function has signature expected by AgentLoopConfig.stream_fn:
    (system_prompt, messages, tools, max_tokens) -> async generator of
    (delta_text, ContentBlock|None)
    """

    async def _stream(
        system_prompt: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        max_tokens: int,
    ) -> AsyncGenerator[tuple[str, Optional[ContentBlock]], None]:
        provider_messages = _messages_to_anthropic(messages)
        tool_defs = _tool_schemas(tools) if tools else None

        async for ev in client.stream(
            messages=provider_messages,
            tools=tool_defs,
            system_prompt=system_prompt,
        ):
            if ev.type == StreamEventType.TEXT_DELTA:
                yield ev.text, None
            elif ev.type == StreamEventType.TOOL_CALL:
                yield "", ContentBlock(
                    type="tool_use",
                    tool_use_id=ev.tool_call_id,
                    tool_name=ev.tool_name,
                    tool_input=ev.tool_input,
                )
            elif ev.type == StreamEventType.ERROR:
                raise RuntimeError(ev.error)
            elif ev.type == StreamEventType.DONE:
                break

    return _stream
