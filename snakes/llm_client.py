from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator


class StreamEventType(str, Enum):
    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    DONE = "done"
    ERROR = "error"


@dataclass
class StreamEvent:
    type: StreamEventType
    text: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class LLMClient:
    provider: str
    model: str

    def __init__(self, provider: str, model: str, api_key: str, *, base_url: str | None = None):
        self.provider = provider
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
        self._client: Any = None

    def _init_client(self) -> None:
        if self._client is not None:
            return

        if self.provider == "anthropic":
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        elif self.provider == "openai":
            import openai
            kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = openai.AsyncOpenAI(**kwargs)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str = "",
        *,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        self._init_client()

        if self.provider == "anthropic":
            async for event in self._stream_anthropic(messages, tools, system_prompt, max_tokens=max_tokens):
                yield event
        elif self.provider == "openai":
            async for event in self._stream_openai(messages, tools, system_prompt, max_tokens=max_tokens):
                yield event

    async def _stream_anthropic(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        system_prompt: str,
        *,
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = tools

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                current_tool_name = ""
                current_tool_id = ""
                current_tool_json = ""

                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if hasattr(block, "text"):
                            pass
                        elif hasattr(block, "name"):
                            current_tool_name = block.name
                            current_tool_id = block.id
                            current_tool_json = ""
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, "text"):
                            yield StreamEvent(
                                type=StreamEventType.TEXT_DELTA,
                                text=delta.text,
                            )
                        elif hasattr(delta, "partial_json"):
                            current_tool_json += delta.partial_json
                    elif event.type == "content_block_stop":
                        if current_tool_name:
                            import json
                            try:
                                tool_input = json.loads(current_tool_json) if current_tool_json else {}
                            except json.JSONDecodeError:
                                tool_input = {}
                            yield StreamEvent(
                                type=StreamEventType.TOOL_CALL,
                                tool_name=current_tool_name,
                                tool_call_id=current_tool_id,
                                tool_input=tool_input,
                            )
                            current_tool_name = ""
                            current_tool_id = ""
                            current_tool_json = ""
                    elif event.type == "message_stop":
                        yield StreamEvent(type=StreamEventType.DONE)
        except Exception as exc:
            yield StreamEvent(type=StreamEventType.ERROR, error=str(exc))

    async def _stream_openai(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        system_prompt: str,
        *,
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        oai_messages: list[dict[str, Any]] = []
        if system_prompt:
            oai_messages.append({"role": "system", "content": system_prompt})
        oai_messages.extend(messages)

        oai_tools: list[dict[str, Any]] | None = None
        if tools:
            oai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                }
                for t in tools
            ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "stream": True,
            "max_tokens": max_tokens,
        }
        if oai_tools:
            kwargs["tools"] = oai_tools

        try:
            tool_calls: dict[int, dict[str, Any]] = {}

            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                if delta.content:
                    yield StreamEvent(
                        type=StreamEventType.TEXT_DELTA,
                        text=delta.content,
                    )

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls:
                            tool_calls[idx] = {
                                "id": tc.id or "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc.id:
                            tool_calls[idx]["id"] = tc.id
                        if tc.function and tc.function.name:
                            tool_calls[idx]["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            tool_calls[idx]["arguments"] += tc.function.arguments

                finish = chunk.choices[0].finish_reason if chunk.choices else None
                if finish:
                    import json
                    for tc_data in tool_calls.values():
                        try:
                            tool_input = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                        except json.JSONDecodeError:
                            tool_input = {}
                        yield StreamEvent(
                            type=StreamEventType.TOOL_CALL,
                            tool_name=tc_data["name"],
                            tool_call_id=tc_data["id"],
                            tool_input=tool_input,
                        )
                    yield StreamEvent(type=StreamEventType.DONE)
        except Exception as exc:
            yield StreamEvent(type=StreamEventType.ERROR, error=str(exc))


def create_llm_client(provider: str, model: str, api_key: str, *, base_url: str | None = None) -> LLMClient:
    return LLMClient(provider=provider, model=model, api_key=api_key, base_url=base_url)
