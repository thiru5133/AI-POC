import json
import logging
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

log = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 3500  # keeps the follow-up model call small enough for per-minute token limits


# Said instead of doing: a reply that promises to look something up without calling the tool leaves the caller waiting
# on silence, and the next turn tends to invent a "system problem".
_STALLING = re.compile(
    r"\b(?:moment|second|sec|hold on|hold the line|bear with me|please wait|one sec)\b"
    r"|\b(?:let me|let's|allow me to|i'll|i will|i'm going to|i am going to|i need to|i'll need to|i will need to"
    r"|i have to|i'll have to|going to|about to)\s+(?:\w+\s+){0,2}?"
    r"(?:check|look|see|find|pull|search|verify|get|fetch|do that|do this|book|reserve|proceed|process|make)\b"
    r"|\bcheck(?:ing)?\s+(?:that|this|it|on)\b|\blooking (?:that |this )?up\b",
    re.IGNORECASE,
)
NUDGE = (
    "You said you would look something up but did not call a tool. Call the right tool now with what the caller "
    "has told you, then answer from its result. If a detail is missing, ask the caller for it instead."
)

ALREADY_BOOKED_NOTE = (
    "This exact booking was already made earlier in this call. Do not book again: tell the caller it is already confirmed."
)
SAID_GOODBYE = re.compile(r"goodbye\W*$", re.IGNORECASE)

NOT_SENT_NOTE = (
    "The confirmation text to the caller's phone could NOT be delivered. Do not say a text was sent; give the caller "
    "the reference aloud instead."
)
_SENT_NOTE = (
    "A confirmation was already sent {where}. Do not send another there; tell the caller it is on its way "
    "(say exactly how it was sent: {how})."
)


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def booking_confirmation_text(profile: DomainProfile, booking: dict[str, Any]) -> str:
    """A short confirmation from whatever the booking tool returned. Which details matter comes from the profile's own
    booking fields, so nothing here knows the business's domain."""
    data = booking.get("result") if isinstance(booking.get("result"), dict) else booking
    required = profile.booking_workflow.required_fields
    dates = [k for k, v in data.items() if isinstance(v, str) and _ISO_DATE.match(v)]
    named = [k for k in data if k.endswith(("_name", "_city", "_number")) and k not in required]
    keys = list(dict.fromkeys([*named, *dates, *required, *(k for k in ("nights",) if k in data)]))
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

    def _wants_text(self, profile: DomainProfile, ctx: ConversationContext) -> bool:
        return bool(
            self.confirmation_channel and ctx.channel == "phone" and ctx.caller.phone and "send_confirmation" in profile.enabled_tools
        )

    async def _confirm_by_text(
        self, profile: DomainProfile, ctx: ConversationContext, booking: dict[str, Any]
    ) -> tuple[str, str] | None:
        """Texts the caller's own number once a booking is made, so confirmation never depends on the assistant
        remembering to. Only on phone calls (the caller ID is known), once per conversation."""
        channel = self.confirmation_channel
        if not (channel and ctx.channel == "phone" and ctx.caller.phone and "send_confirmation" in profile.enabled_tools):
            return None
        if ctx.notifications_sent or ctx.notify_target:
            return None
        message = booking_confirmation_text(profile, booking)
        sent, is_error = await self.tools.execute(
            "send_confirmation", ctx, {"channel": channel, "to": ctx.caller.phone, "message": message}
        )
        if not is_error and sent.get("sent"):
            return "to the caller's phone", f"by {'WhatsApp' if channel == 'whatsapp' else 'text message'}"
        log.warning("booking confirmation text could not be delivered", extra={"tenant_id": ctx.tenant_id, "to": ctx.caller.phone})
        return None

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
        used_tool = False
        nudged = False
        was_handoff = ctx.handoff_requested
        for _ in range(self.max_tool_rounds + 1):
            text_parts: list[str] = []
            calls = []
            async for event in self.llm.stream(system, messages, tool_defs):
                if event.type == "text":
                    text_parts.append(event.text)
                    yield event.text
                else:
                    calls.append(event)
            if (
                not calls
                and tool_defs
                and not used_tool
                and not nudged
                and _STALLING.search("".join(text_parts))
                and not "".join(text_parts).rstrip().endswith("?")
            ):
                nudged = True  # promised a look-up, called nothing: make it do what it said (once per turn)
                messages.append({"role": "assistant", "content": "".join(text_parts)})
                messages.append({"role": "user", "content": NUDGE})
                continue
            if not calls:
                # A call is finished once a booking is made, or once a person has been promised who will call back
                # (nobody can take it live): say goodbye so the line is dropped instead of left open and billed.
                # Not while the assistant waits for an answer, and never on an emergency.
                call_back = ctx.handoff_requested and not was_handoff and not ctx.transfer_available
                if (
                    (booked or call_back)
                    and ctx.channel == "phone"
                    and ctx.urgency != "emergency"
                    and not "".join(text_parts).rstrip().endswith("?")
                    and not SAID_GOODBYE.search("".join(text_parts).strip())  # it already said it itself
                ):
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
            used_tool = True
            for call in calls:
                signature = f"{call.tool_name}:{json.dumps(call.tool_input, sort_keys=True)}"
                if usage.is_booking_tool(call.tool_name) and signature in ctx.booked_calls:
                    # "Book it" said twice (or a repeated request) must not make a second booking.
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call.tool_id,
                            "content": json.dumps({"note": ALREADY_BOOKED_NOTE}),
                            "is_error": False,
                        }
                    )
                    continue
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
                        ctx.booked_calls.append(signature)
                        sent_how = await self._confirm_by_text(profile, ctx, output)
                        if sent_how:
                            output = {**output, "note": _SENT_NOTE.format(where=sent_how[0], how=sent_how[1])}
                        elif self._wants_text(profile, ctx):
                            output = {**output, "note": NOT_SENT_NOTE}
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.tool_id,
                        "content": json.dumps(output)[:MAX_TOOL_RESULT_CHARS],
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": results})
