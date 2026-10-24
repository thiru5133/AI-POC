import json
import re
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


CONFIRMATION_NOTE = (
    "A confirmation text was already sent to the caller's phone. Do not send another to that number; "
    "tell them it is on its way."
)


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def booking_confirmation_text(profile: DomainProfile, booking: dict[str, Any]) -> str:
    """A short confirmation from whatever the booking tool returned. Which details matter comes from the profile's own
    booking fields, so nothing here knows the business's domain."""
    data = booking.get("result") if isinstance(booking.get("result"), dict) else booking
    required = profile.booking_workflow.required_fields
    dates = [k for k, v in data.items() if isinstance(v, str) and _ISO_DATE.match(v)]
    named = [k for k in data if k.endswith("_name") and k not in required]
    keys = list(dict.fromkeys([*named, *dates, *required]))
    details = [
        f"{key.replace('_', ' ')} {data[key]}"
        for key in keys
        if isinstance(data.get(key), (str, int, float)) and data[key] != ""
    ]
    total = next((data[k] for k in data if k.startswith("total") and isinstance(data[k], (int, float))), None)
    parts = [f"{profile.identity.organization_name}: your booking is confirmed."]
    if data.get("reference"):
        parts.append(f"Reference {data['reference']}.")
    if details:
        parts.append(", ".join(details) + ".")
    if total is not None:
        parts.append(f"Total {total}.")
    parts.append("Thank you!")
    return " ".join(parts)[:480]


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
        confirmation_channel: str = "",
    ):
        self.confirmation_channel = confirmation_channel
        self.llm = llm
        self.tools = tools or ToolRegistry()
        self.mcp = mcp
        self.max_tool_rounds = max_tool_rounds

    async def _confirm_by_text(self, profile: DomainProfile, ctx: ConversationContext, booking: dict[str, Any]) -> bool:
        """Texts the caller's own number once a booking is made, so confirmation never depends on the assistant
        remembering to. Only on phone calls (the caller ID is known), once per conversation."""
        channel = self.confirmation_channel
        if not (channel and ctx.channel == "phone" and ctx.caller.phone and "send_confirmation" in profile.enabled_tools):
            return False
        if ctx.notifications_sent or ctx.notify_target:
            return False
        message = booking_confirmation_text(profile, booking)
        sent, is_error = await self.tools.execute(
            "send_confirmation", ctx, {"channel": channel, "to": ctx.caller.phone, "message": message}
        )
        return not is_error and bool(sent.get("sent"))

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
                if is_error and mcp_tools and mcp_tools.owns(call.tool_name) and not ctx.alert_reason:
                    # The business's own system failed: its people hear about it even if the caller hangs up.
                    ctx.alert_reason = f"The business's system failed ({call.tool_name.rsplit('__', 1)[-1]})."[:200]
                if not is_error:
                    ctx.record_usage(usage.TOOL_CALL)
                    if usage.is_booking_tool(call.tool_name):
                        ctx.record_usage(usage.BOOKING)
                        booked = True
                        if await self._confirm_by_text(profile, ctx, output):
                            output = {**output, "note": CONFIRMATION_NOTE}
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.tool_id,
                        "content": json.dumps(output)[:MAX_TOOL_RESULT_CHARS],
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": results})
