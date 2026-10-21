from datetime import datetime
from zoneinfo import ZoneInfo

from app.conversation.context import ConversationContext
from app.domain.hours import describe, is_open, next_opening
from app.domain.profile import DomainProfile

REFUSAL = "I'm sorry, I don't have that information."

_STYLE = {
    "formal": "Speak in a polished, formal and courteous tone.",
    "conversational": "Speak in a warm, friendly, conversational tone.",
    "urgent": "Speak calmly, concisely and with a sense of urgency.",
}


def _now(timezone: str) -> datetime:
    try:
        return datetime.now(ZoneInfo(timezone))
    except Exception:
        return datetime.now(ZoneInfo("UTC"))


def _today(timezone: str) -> str:
    return _now(timezone).strftime("%A, %Y-%m-%d")


def _hours_lines(ident) -> list[str]:
    """Operating hours and whether the business is open at this moment (empty hours = always open)."""
    if not ident.hours:
        return []
    now = _now(ident.timezone)
    lines = [f"Operating hours ({ident.timezone}): {describe(ident.hours)}."]
    if is_open(ident.hours, now):
        return lines + ["The business is open right now."]
    reopens = next_opening(ident.hours, now)
    closed = (
        "The business is CLOSED right now. Tell the caller it is closed and when it opens again"
        f"{f' ({reopens})' if reopens else ''}; do not promise that a staff member can answer now."
    )
    if ident.after_hours_message:
        closed += f" Guidance for after-hours callers: {ident.after_hours_message}"
    return lines + [closed]


def build_system_prompt(profile: DomainProfile, ctx: ConversationContext, tools_available: bool = False) -> str:
    """Build the system prompt purely from the active domain profile — no domain wording lives here."""
    ident = profile.identity
    kb = profile.knowledge_base

    parts = [
        f"You are the {ident.persona} for {ident.organization_name}, speaking with a caller over the phone.",
        _STYLE.get(ident.voice_style, _STYLE["conversational"]),
        f"Today's date is {_today(ident.timezone)}; use it to interpret dates such as 'tomorrow' or 'next Friday'.",
        *_hours_lines(ident),
        "Your replies are spoken aloud: keep them short (one to three sentences), natural, "
        "and free of markdown, lists, emojis or special symbols.",
        "",
        "KNOWLEDGE BASE (your only source of facts about the organization):",
    ]
    for faq in kb.faqs:
        parts.append(f"Q: {faq.question}\nA: {faq.answer}")
    for label, value in kb.info.items():
        parts.append(f"{label}: {value}")
    parts += [
        "",
        "RULES:",
        "- Answer organization-specific questions ONLY from the knowledge base above or from tool results.",
        f'- If the answer is not available, reply exactly: "{REFUSAL}"',
        "- Never invent availability, prices, bookings or policies.",
        "- If the caller asks for a human, say you will connect them to a person.",
        "- Remember what the caller has already told you and do not ask for it again.",
    ]
    if tools_available:
        parts += [
            "- You have tools connected to this organization's own systems. Use them to look up live information "
            "(availability, prices, bookings) and to carry out requests; never guess what a tool can tell you.",
            "- Before an action that changes something (a booking or cancellation), confirm the details with the "
            "caller. Dates passed to tools must be exact, in the format the tool asks for.",
            "- Read results back naturally; never read out technical ids, JSON or field names.",
        ]
    if ctx.entities:
        parts += ["", f"INFORMATION ALREADY COLLECTED: {ctx.entities}"]
    return "\n".join(parts)
