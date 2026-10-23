from typing import Any

from pydantic import BaseModel, Field, PrivateAttr


class Caller(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None


class ConversationContext(BaseModel):
    """Domain-neutral conversation state.

    Domain slots live in `entities`, keyed by the active profile's `bookingWorkflow.requiredFields`
    — the engine never names them.
    """

    session_id: str
    tenant_id: str
    domain_profile_id: str
    intent: str | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    caller: Caller = Field(default_factory=Caller)
    workflow_state: str | None = None
    last_action: str | None = None
    urgency: str = "normal"  # normal | frustrated | urgent | emergency; only ever raised (see tools/builtin.py)
    urgency_reason: str | None = None
    channel: str = "web"  # web | phone
    call_sid: str | None = None  # the carrier's id for the live call, when channel is phone
    transfer_available: bool = False  # a call can be handed to a person right now (a number is set and it is open)
    handoff_requested: bool = False  # the caller asked for a person (set by the request_human tool)
    handoff_reason: str | None = None
    # The number callers dial, from the business's Phone page. Looked up on every turn (so a change applies at once)
    # and never saved with the conversation.
    business_phone: str | None = None
    pending_offer: str | None = None  # a system problem we offered a person for; waiting for the caller's yes or no
    staff_alerted: bool = False  # the business's people were pinged about this conversation (once)
    notifications_sent: int = 0  # confirmations sent in this conversation (capped, see tools/builtin.py)
    notify_target: str | None = None  # the one phone number / email address those went to

    # Usage events of the current turn (not persisted with the context): the engine and tools add to it, the
    # conversation service writes them to the usage log when it saves the turn.
    _usage: list[tuple[str, int]] = PrivateAttr(default_factory=list)

    def record_usage(self, kind: str, quantity: int = 1) -> None:
        self._usage.append((kind, quantity))

    @property
    def usage_log(self) -> list[tuple[str, int]]:
        return list(self._usage)
