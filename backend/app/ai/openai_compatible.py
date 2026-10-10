import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.ai.base import LLMEvent, LLMProvider, ToolDefinition


def to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the engine's Anthropic-style blocks into OpenAI chat messages."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for msg in messages:
        content = msg["content"]
        if isinstance(content, str):
            out.append({"role": msg["role"], "content": content})
            continue
        if msg["role"] == "assistant":
            text = "".join(b["text"] for b in content if b["type"] == "text")
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b["input"])},
                }
                for b in content
                if b["type"] == "tool_use"
            ]
            entry: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
        else:
            for b in content:
                if b["type"] == "tool_result":
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
                elif b["type"] == "text":
                    out.append({"role": "user", "content": b["text"]})
    return out


class OpenAICompatibleProvider(LLMProvider):
    """Works with any OpenAI-compatible chat API (Groq, OpenAI, Gemini's compat endpoint, Ollama)."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None, max_tokens: int = 512):
        self._client = AsyncOpenAI(api_key=api_key or "none", base_url=base_url)
        self._model = model
        self._max_tokens = max_tokens

    async def stream(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolDefinition]
    ) -> AsyncIterator[LLMEvent]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": to_openai_messages(system, messages),
            "max_tokens": self._max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
                for t in tools
            ]
        pending: dict[int, dict[str, str]] = {}
        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield LLMEvent(type="text", text=delta.content)
            for tc in delta.tool_calls or []:
                slot = pending.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                slot["id"] = tc.id or slot["id"]
                if tc.function:
                    slot["name"] = tc.function.name or slot["name"]
                    slot["args"] += tc.function.arguments or ""
        for _, call in sorted(pending.items()):
            yield LLMEvent(
                type="tool_use",
                tool_id=call["id"],
                tool_name=call["name"],
                tool_input=json.loads(call["args"] or "{}"),
            )
