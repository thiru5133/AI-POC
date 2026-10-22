"""What is metered per business. Kinds are stored as strings in `usage_events`; quantities are summed per period."""

import re

CONVERSATION = "conversation"  # a chat or call started
MESSAGE = "message"  # one thing the caller said
VOICE_SECONDS = "voice_seconds"  # length of a voice call
TOOL_CALL = "tool_call"  # a tool the assistant ran successfully (the business's own or a platform tool)
BOOKING = "booking"  # a successful tool call that books something; an estimate, see is_booking_tool
CONFIRMATION = "confirmation"  # an SMS / WhatsApp / email confirmation that was sent

KINDS = (CONVERSATION, MESSAGE, VOICE_SECONDS, TOOL_CALL, BOOKING, CONFIRMATION)

_BOOKING_TOOL = re.compile(r"^(book|reserve|schedule|create_(booking|reservation|appointment))", re.IGNORECASE)


def is_booking_tool(tool_name: str) -> bool:
    """Whether a tool looks like it books something, judging by its name (the part after the 'server__' prefix).

    The platform cannot see inside a business's system, so bookings are an estimate: a business whose booking tool is
    named differently is under-counted.
    """
    return bool(_BOOKING_TOOL.match(tool_name.rsplit("__", 1)[-1]))
