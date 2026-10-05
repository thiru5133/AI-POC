from typing import Any

from pydantic import BaseModel, Field


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
