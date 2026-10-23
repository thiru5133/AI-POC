from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class LLMEvent:
    type: Literal["text", "tool_use"]
    text: str = ""
    tool_id: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    # Provider-specific data that must be echoed back with the call (e.g. Gemini's thought signature).
    provider_data: dict[str, Any] | None = None


class LLMBusyError(Exception):
    """The model provider is rate limiting us (too many requests or tokens right now). Not a fault in the assistant."""


class LLMProvider(ABC):
    """Provider-neutral streaming interface.

    `messages` use Anthropic-style content: {"role": "user"|"assistant", "content": str | list[block]},
    where blocks are {"type": "text"|"tool_use"|"tool_result", ...}.
    """

    @abstractmethod
    def stream(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolDefinition]
    ) -> AsyncIterator[LLMEvent]: ...
