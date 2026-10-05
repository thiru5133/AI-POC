import logging
from typing import Any

from app.ai.base import ToolDefinition
from app.conversation.context import ConversationContext
from app.domain.profile import DomainProfile
from app.tools.base import Tool

log = logging.getLogger(__name__)


class ToolRegistry:
    """Holds all registered tools; a profile's `enabledTools` decides which the LLM sees."""

    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {t.name: t for t in tools or []}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def definitions_for(self, profile: DomainProfile) -> list[ToolDefinition]:
        return [t.definition() for n, t in self._tools.items() if n in profile.enabled_tools]

    async def execute(
        self, name: str, ctx: ConversationContext, tool_input: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """Returns (result, is_error). Errors are reported back to the LLM, never raised into the call."""
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool '{name}'"}, True
        try:
            return await tool.handler(ctx, tool_input), False
        except Exception as exc:
            log.exception("tool failed", extra={"tool": name, "tenant_id": ctx.tenant_id})
            return {"error": f"Tool '{name}' failed: {exc}"}, True
