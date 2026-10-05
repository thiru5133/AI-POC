from collections.abc import AsyncIterator, Callable
from typing import Any

from app.ai.base import LLMEvent, LLMProvider, ToolDefinition


class FakeLLMProvider(LLMProvider):
    """Deterministic provider for tests and key-less demos. Records every call it receives."""

    def __init__(self, responder: Callable[[str, list[dict[str, Any]]], str] | None = None):
        self._responder = responder or (lambda system, messages: "This is a fake reply.")
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolDefinition]
    ) -> AsyncIterator[LLMEvent]:
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        reply = self._responder(system, messages)
        words = reply.split(" ")
        for i, word in enumerate(words):
            yield LLMEvent(type="text", text=word + (" " if i < len(words) - 1 else ""))
