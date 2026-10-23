"""Tools the platform itself provides, as opposed to a business's own MCP tools. A profile turns them on through
`enabledTools`; the handler (not the LLM) performs the action."""

import asyncio
import logging
import re
from typing import Any

from app import usage
from app.conversation.context import ConversationContext
from app.core.errors import AppError
from app.notifications.messaging import MessageSender
from app.tools.base import Tool

log = logging.getLogger(__name__)

MAX_CONFIRMATIONS_PER_CONVERSATION = 3
MAX_MESSAGE_CHARS = 480
_PHONE = re.compile(r"^\+[1-9]\d{7,14}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize(channel: str, to: str) -> str | None:
    """The destination in canonical form, or None when it does not suit the channel."""
    if channel == "email":
        return to.strip().lower() if _EMAIL.match(to.strip()) else None
    phone = re.sub(r"[\s\-().]", "", to)
    return phone if _PHONE.match(phone) else None


def request_human_tool() -> Tool:
    async def handler(ctx: ConversationContext, args: dict[str, Any]) -> dict[str, Any]:
        ctx.handoff_requested = True
        ctx.handoff_reason = str(args.get("reason") or "")[:200] or None
        if ctx.transfer_available:
            note = (
                "The call is being transferred to a staff member right now. In one short sentence, tell the caller "
                "to hold while you connect them."
            )
        else:
            note = (
                "A staff member will follow up with the caller. A live transfer is not available right now, so tell "
                "the caller someone will contact them; do not say they are being connected right now."
            )
        return {"status": "recorded", "note": note}

    return Tool(
        "request_human",
        "Record that the caller wants to speak to a person. Use when they ask for a human, or you cannot help.",
        {
            "type": "object",
            "properties": {"reason": {"type": "string", "description": "Why the caller needs a person, in a few words."}},
        },
        handler,
    )


URGENCY_LEVELS = ("frustrated", "urgent", "emergency")
_URGENCY_RANK = {"normal": 0, "frustrated": 1, "urgent": 2, "emergency": 3}
_URGENCY_NOTES = {
    "frustrated": "Apologise briefly, keep helping, and offer to have a person follow up if it does not get better.",
    "urgent": "Treat this as a priority: help with the most important thing first and say a staff member will "
    "follow up as soon as possible.",
    "emergency": "Follow the EMERGENCY instruction in your rules right now, before anything else, and keep it short.",
}


def flag_urgency_tool() -> Tool:
    async def handler(ctx: ConversationContext, args: dict[str, Any]) -> dict[str, Any]:
        level = str(args.get("level", ""))
        if level not in URGENCY_LEVELS:
            return {"recorded": False, "reason": f"level must be one of: {', '.join(URGENCY_LEVELS)}."}
        if _URGENCY_RANK[level] > _URGENCY_RANK[ctx.urgency]:  # only ever raised within a conversation
            ctx.urgency = level
            ctx.urgency_reason = str(args.get("reason") or "")[:200] or None
        if level in ("urgent", "emergency"):
            ctx.handoff_requested = True
            ctx.handoff_reason = ctx.handoff_reason or ctx.urgency_reason or level
        return {"recorded": True, "urgency": ctx.urgency, "note": _URGENCY_NOTES[level]}

    return Tool(
        "flag_urgency",
        "Flag the caller's state so staff can see it. Call it as soon as the caller sounds frustrated or angry, "
        "describes something urgent, or describes an emergency (danger to life, injury, serious illness, fire, crime).",
        {
            "type": "object",
            "properties": {
                "level": {"type": "string", "enum": list(URGENCY_LEVELS)},
                "reason": {"type": "string", "description": "What the caller said or showed, in a few words."},
            },
            "required": ["level"],
        },
        handler,
    )


def send_confirmation_tool(senders: dict[str, MessageSender]) -> Tool:
    async def handler(ctx: ConversationContext, args: dict[str, Any]) -> dict[str, Any]:
        channel = str(args.get("channel", ""))
        message = str(args.get("message", "")).strip()
        if channel not in senders:
            return {"sent": False, "reason": f"Unknown channel; use one of: {', '.join(sorted(senders))}."}
        if not message or len(message) > MAX_MESSAGE_CHARS:
            return {"sent": False, "reason": f"The message must be 1 to {MAX_MESSAGE_CHARS} characters."}
        to = _normalize(channel, str(args.get("to", "")))
        if to is None:
            return {"sent": False, "reason": "That is not a valid phone number (with country code) or email address."}
        # The LLM chooses the destination, so a caller could try to make it message other people: keep to the first
        # number or address given, and cap how many messages one conversation can send.
        if ctx.notifications_sent >= MAX_CONFIRMATIONS_PER_CONVERSATION:
            return {"sent": False, "reason": "The limit of confirmation messages for this conversation was reached."}
        if ctx.notify_target not in (None, to):
            return {"sent": False, "reason": "Messages can only go to the contact the caller gave first."}
        try:
            await asyncio.to_thread(senders[channel].send, to, message)
        except AppError as exc:
            log.warning("confirmation not sent", extra={"tenant_id": ctx.tenant_id, "channel": channel, "error": exc.message})
            return {"sent": False, "reason": "The message could not be delivered."}
        ctx.notifications_sent += 1
        ctx.notify_target = to
        ctx.record_usage(usage.CONFIRMATION)
        return {"sent": True, "channel": channel}

    return Tool(
        "send_confirmation",
        "Send the caller a short text confirmation of a booking or change once it is done and they gave their phone "
        "number (with country code) or email address. Never send before the booking succeeded.",
        {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": sorted(senders)},
                "to": {"type": "string", "description": "Phone number with country code, or email address."},
                "message": {"type": "string", "description": "The confirmation text, under 480 characters."},
            },
            "required": ["channel", "to", "message"],
        },
        handler,
    )


def builtin_tools(senders: dict[str, MessageSender]) -> list[Tool]:
    return [request_human_tool(), send_confirmation_tool(senders), flag_urgency_tool()]
