from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from app.ai.base import LLMEvent, LLMProvider, ToolDefinition


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int = 512):
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    async def stream(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolDefinition]
    ) -> AsyncIterator[LLMEvent]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools
            ]
        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield LLMEvent(type="text", text=text)
            final = await stream.get_final_message()
        for block in final.content:
            if block.type == "tool_use":
                yield LLMEvent(type="tool_use", tool_id=block.id, tool_name=block.name, tool_input=block.input)
