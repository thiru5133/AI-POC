import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI, RateLimitError

from app.ai.base import LLMBusyError, LLMEvent, LLMProvider, ToolDefinition


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
                    **({"extra_content": b["provider_data"]} if b.get("provider_data") else {}),
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

MAX_RATE_LIMIT_RETRIES = 2
MAX_RETRY_WAIT_SECONDS = 5.0  # a caller on the phone will not wait longer than this


def _retry_wait(exc: RateLimitError) -> float | None:
    """Seconds the provider asks us to wait, or None when it is too long for a live call (e.g. a daily quota)."""
    try:
        wait = float(exc.response.headers.get("retry-after", ""))
    except (ValueError, AttributeError):
        wait = 2.0
    return wait if wait <= MAX_RETRY_WAIT_SECONDS else None


class OpenAICompatibleProvider(LLMProvider):
    """Works with any OpenAI-compatible chat API (Groq, OpenAI, Gemini's compat endpoint, Ollama)."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None, max_tokens: int = 512):
        # No silent retries: the client would wait 10-20 s on a rate limit, long enough for a live phone call to time out.
        self._client = AsyncOpenAI(api_key=api_key or "none", base_url=base_url, max_retries=0)
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
        pending: dict[int, dict[str, Any]] = {}
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            try:
                stream = await self._client.chat.completions.create(**kwargs)
                break
            except RateLimitError as exc:
                wait = _retry_wait(exc)
                if wait is None or attempt == MAX_RATE_LIMIT_RETRIES:
                    raise LLMBusyError(str(exc)) from exc
                await asyncio.sleep(wait + 0.2)
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield LLMEvent(type="text", text=delta.content)
            for tc in delta.tool_calls or []:
                slot = pending.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                slot["id"] = tc.id or slot["id"]
                extra = (tc.model_extra or {}).get("extra_content")
                if extra:
                    slot["extra"] = extra
                if tc.function:
                    slot["name"] = tc.function.name or slot["name"]
                    slot["args"] += tc.function.arguments or ""
        for _, call in sorted(pending.items()):
            yield LLMEvent(
                type="tool_use",
                tool_id=call["id"],
                tool_name=call["name"],
                tool_input=json.loads(call["args"] or "{}"),
                provider_data=call.get("extra"),
            )
