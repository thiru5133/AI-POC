from app.conversation.context import ConversationContext
from app.domain.profile import DomainProfile

REFUSAL = "I'm sorry, I don't have that information."

_STYLE = {
    "formal": "Speak in a polished, formal and courteous tone.",
    "conversational": "Speak in a warm, friendly, conversational tone.",
    "urgent": "Speak calmly, concisely and with a sense of urgency.",
}


def build_system_prompt(profile: DomainProfile, ctx: ConversationContext) -> str:
    """Build the system prompt purely from the active domain profile — no domain wording lives here."""
    ident = profile.identity
    kb = profile.knowledge_base

    parts = [
        f"You are the {ident.persona} for {ident.organization_name}, speaking with a caller over the phone.",
        _STYLE.get(ident.voice_style, _STYLE["conversational"]),
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
    if ctx.entities:
        parts += ["", f"INFORMATION ALREADY COLLECTED: {ctx.entities}"]
    return "\n".join(parts)
