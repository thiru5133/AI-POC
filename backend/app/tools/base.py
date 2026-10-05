from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.ai.base import ToolDefinition
from app.conversation.context import ConversationContext

ToolHandler = Callable[[ConversationContext, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class Tool:
    """A backend operation the LLM may request. The handler (not the LLM) performs the business action."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler

    def definition(self) -> ToolDefinition:
        return ToolDefinition(self.name, self.description, self.input_schema)
