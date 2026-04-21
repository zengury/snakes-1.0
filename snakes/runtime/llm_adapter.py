from __future__ import annotations

import hashlib
import json
import re
from typing import Any, AsyncGenerator, Optional

from snakes.llm_client import LLMClient, StreamEventType
from snakes.types import AgentMessage, AgentTool, ContentBlock


_ALLOWED_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def _encode_tool_name(name: str) -> str:
    """Encode internal tool names into provider-safe function names.

    Anthropic/OpenAI tool names must match ^[a-zA-Z0-9_-]{1,128}$.
    Our internal naming uses dots (camera.get) and occasionally other chars.

    Keep encoding deterministic and injective enough for our namespace.
    """

    out: list[str] = []
    for ch in name:
        if ch.isalnum() or ch in ("_", "-"):
            out.append(ch)
        elif ch == ".":
            out.append("__dot__")
        elif ch == ":":
            out.append("__col__")
        elif ch == "/":
            out.append("__sl__")
        else:
            out.append(f"__u{ord(ch):04x}__")

    enc = "".join(out)
    if len(enc) > 128:
        h = hashlib.sha1(enc.encode("utf-8")).hexdigest()[:10]
        enc = enc[:110] + "_" + h

    # Final sanity fallback
    if not _ALLOWED_RE.match(enc):
        h = hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
        enc = "tool_" + h

    return enc


def _tool_schemas(tools: list[AgentTool]) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str]]:
    """Return (tool_defs, internal->provider, provider->internal)."""

    i2p: dict[str, str] = {}
    p2i: dict[str, str] = {}
    defs: list[dict[str, Any]] = []

    for t in tools:
        provider_name = _encode_tool_name(t.name)
        i2p[t.name] = provider_name
        p2i[provider_name] = t.name
        defs.append(
            {
                "name": provider_name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
        )

    return defs, i2p, p2i


def _block_to_anthropic(block: ContentBlock, *, i2p: dict[str, str]) -> dict[str, Any]:
    if block.type == "text":
        return {"type": "text", "text": block.text or ""}
    if block.type == "tool_use":
        internal = block.tool_name or ""
        provider_name = i2p.get(internal, _encode_tool_name(internal))
        return {
            "type": "tool_use",
            "id": block.tool_use_id or "",
            "name": provider_name,
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


def _messages_to_anthropic(messages: list[AgentMessage], *, i2p: dict[str, str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for m in messages:
        if m.role not in ("user", "assistant"):
            continue
        content = [_block_to_anthropic(b, i2p=i2p) for b in m.content]
        result.append({"role": m.role, "content": content})
    return result


def make_stream_fn(client: LLMClient) -> Any:
    """Build AgentLoopConfig.stream_fn from LLMClient.

    Handles provider tool-name constraints by mapping internal tool names
    (camera.get) to provider-safe names.
    """

    async def _stream(
        system_prompt: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        max_tokens: int,
    ) -> AsyncGenerator[tuple[str, Optional[ContentBlock]], None]:
        tool_defs, i2p, p2i = _tool_schemas(tools) if tools else (None, {}, {})
        provider_messages = _messages_to_anthropic(messages, i2p=i2p)

        async for ev in client.stream(
            messages=provider_messages,
            tools=tool_defs,
            system_prompt=system_prompt,
        ):
            if ev.type == StreamEventType.TEXT_DELTA:
                yield ev.text, None
            elif ev.type == StreamEventType.TOOL_CALL:
                internal_name = p2i.get(ev.tool_name, ev.tool_name)
                yield "", ContentBlock(
                    type="tool_use",
                    tool_use_id=ev.tool_call_id,
                    tool_name=internal_name,
                    tool_input=ev.tool_input,
                )
            elif ev.type == StreamEventType.ERROR:
                raise RuntimeError(ev.error)
            elif ev.type == StreamEventType.DONE:
                break

    return _stream
