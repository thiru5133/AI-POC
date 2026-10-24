import json
from collections.abc import AsyncIterator
from typing import Any

from app import usage
from app.ai.base import LLMProvider
from app.conversation.context import CALL_CLOSING, ConversationContext
from app.conversation.prompt import build_system_prompt
from app.domain.profile import DomainProfile
from app.mcp.tools import McpToolSource
from app.tools.registry import ToolRegistry

MAX_TOOL_RESULT_CHARS = 3500  # keeps the follow-up model call small enough for per-minute token limits


class ConversationEngine:
    """Domain-agnostic turn runner: prompt from profile -> LLM -> (tool loop) -> streamed text.

    Pure with respect to storage: callers pass history in and persist results themselves.
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry | None = None,
        max_tool_rounds: int = 4,
        mcp: McpToolSource | None = None,
    ):
        self.llm = llm
        self.tools = tools or ToolRegistry()
        self.mcp = mcp
        self.max_tool_rounds = max_tool_rounds

    async def run_turn(
        self,
        profile: DomainProfile,
        ctx: ConversationContext,
        history: list[dict[str, Any]],
        user_text: str,
    ) -> AsyncIterator[str]:
        # The tenant's own MCP tools, built from that tenant's configuration only (ctx.tenant_id comes from the
        # authenticated session, never from client input).
        mcp_tools = await self.mcp.for_tenant(ctx.tenant_id) if self.mcp else None
        tool_defs = self.tools.definitions_for(profile) + (mcp_tools.definitions if mcp_tools else [])
        system = build_system_prompt(profile, ctx, tools_available=bool(tool_defs))
        messages = [*history, {"role": "user", "content": user_text}]

        booked = False
        for _ in range(self.max_tool_rounds + 1):
            text_parts: list[str] = []
            calls = []
            async for event in self.llm.stream(system, messages, tool_defs):
                if event.type == "text":
                    text_parts.append(event.text)
                    yield event.text
                else:
                    calls.append(event)
            if not calls:
                # A booked call is finished: say goodbye so the line is dropped, unless the assistant is still
                # waiting for an answer from the caller.
                if booked and ctx.channel == "phone" and not "".join(text_parts).rstrip().endswith("?"):
                    yield f" {CALL_CLOSING}"
                return

            blocks: list[dict[str, Any]] = []
            if "".join(text_parts).strip():
                blocks.append({"type": "text", "text": "".join(text_parts)})
            blocks += [
                {
                    "type": "tool_use",
                    "id": c.tool_id,
                    "name": c.tool_name,
                    "input": c.tool_input,
                    **({"provider_data": c.provider_data} if c.provider_data else {}),
                }
                for c in calls
            ]
            messages.append({"role": "assistant", "content": blocks})

            results = []
            for call in calls:
                if mcp_tools and mcp_tools.owns(call.tool_name):
                    output, is_error = await mcp_tools.execute(call.tool_name, call.tool_input)
                else:
                    output, is_error = await self.tools.execute(call.tool_name, ctx, call.tool_input)
                ctx.last_action = call.tool_name
                if not is_error:
                    ctx.record_usage(usage.TOOL_CALL)
                    if usage.is_booking_tool(call.tool_name):
                        ctx.record_usage(usage.BOOKING)
                        booked = True
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.tool_id,
                        "content": json.dumps(output)[:MAX_TOOL_RESULT_CHARS],
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": results})
