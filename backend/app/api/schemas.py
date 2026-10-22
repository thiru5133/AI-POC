from datetime import datetime
from typing import Literal, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CreateConversationResponse(CamelModel):
    id: str
    greeting: str


class SendMessageRequest(CamelModel):
    text: str


class SendMessageResponse(CamelModel):
    reply: str
    intent: str | None = None


class MessageOut(CamelModel):
    role: str
    text: str
    intent: str | None = None
    created_at: datetime


class ConversationSummary(CamelModel):
    id: str
    started_at: datetime
    status: str
    urgency: str = "normal"  # normal | frustrated | urgent | emergency
    handoff_requested: bool = False
    message_count: int
    last_message_at: datetime | None
    preview: str  # the caller's first message


class ConversationList(CamelModel):
    items: list[ConversationSummary]
    total: int
    limit: int
    offset: int


class ConversationOut(CamelModel):
    id: str
    domain_profile_id: str
    status: str
    started_at: datetime
    context: dict[str, Any]
    messages: list[MessageOut]


class AudioInfo(CamelModel):
    mime_type: str


class VoiceSessionRequest(CamelModel):
    conversation_id: str


class VoiceSessionResponse(CamelModel):
    conversation_id: str
    transport: str
    ws_path: str | None
    audio: AudioInfo


class DomainProfileOut(CamelModel):
    id: str
    name: str
    domain_type: str
    config: dict[str, Any]


# ---- auth ----
class RegisterRequest(CamelModel):
    """Customer sign-up."""

    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Name is required")
        return value


class LoginRequest(CamelModel):
    identifier: str = Field(min_length=1, max_length=320)  # the account email
    password: str = Field(min_length=1, max_length=128)


class UserOut(CamelModel):
    id: str
    name: str
    email: str
    role: str
    status: str
    tenant_id: str | None = None


class LoginResponse(CamelModel):
    access_token: str | None = None
    user: UserOut | None = None
    otp_required: bool = False  # true on a first login: a code was emailed to `email`
    email: str | None = None


class VerifyOtpRequest(CamelModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)


class ResendOtpRequest(CamelModel):
    email: EmailStr


# ---- businesses (tenants), managed by the superadmin ----
class DomainOut(CamelModel):
    id: str
    key: str
    name: str
    description: str


class BusinessCreate(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    domain_id: str = Field(min_length=1, max_length=36)
    admin_name: str = Field(min_length=1, max_length=200)
    admin_email: EmailStr

    @field_validator("name", "admin_name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("This field is required")
        return value


class BusinessUpdate(CamelModel):
    is_active: bool


class BusinessOut(CamelModel):
    id: str
    name: str
    is_active: bool
    created_at: datetime
    domain_id: str | None = None
    domain_name: str | None = None
    admin_name: str | None = None
    admin_email: str | None = None


class BusinessPublicOut(CamelModel):
    id: str
    name: str
    domain_name: str | None = None
    is_marketplace: bool = False


class UserSummaryOut(CamelModel):
    id: str
    name: str
    email: str
    role: str
    status: str
    tenant_id: str | None = None
    created_at: datetime


class UserListOut(CamelModel):
    items: list[UserSummaryOut]
    total: int
    limit: int
    offset: int
    counts: dict[str, int]  # per status, for the current role/search


class UserDetailOut(UserSummaryOut):
    tenant_name: str | None = None


# ---- MCP integrations ----
def _clean_name(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("Name is required")
    return value


class McpHeaderIn(CamelModel):
    name: str = Field(min_length=1, max_length=60)
    value: str | None = Field(default=None, max_length=2000)  # blank on a saved secret header = keep the saved value
    secret: bool = False


class McpHeaderOut(CamelModel):
    name: str
    secret: bool
    value: str | None  # null for secret headers: they are never sent back
    has_value: bool


Transport = Literal["streamable_http", "sse"]


class McpServerCreate(CamelModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=500)
    headers: list[McpHeaderIn] = []
    transport: Transport = "streamable_http"
    timeout_seconds: int = Field(default=15, ge=1, le=60)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)


class McpServerUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=1, max_length=500)
    headers: list[McpHeaderIn] | None = None  # the complete new list; omit to leave the headers unchanged
    transport: Transport | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return _clean_name(value) if value is not None else None


class McpServerOut(CamelModel):
    id: str
    name: str
    url: str
    enabled: bool
    headers: list[McpHeaderOut]
    transport: str
    timeout_seconds: int
    created_at: datetime


class McpToolOut(CamelModel):
    name: str
    description: str


class McpTestOut(CamelModel):
    ok: bool
    error: str | None = None
    tools: list[McpToolOut]


# ---- usage metering ----
class UsageOut(CamelModel):
    period_days: int
    since: datetime
    conversations: int
    messages: int
    voice_minutes: float
    tool_calls: int
    bookings: int  # estimated from tool names, see app/usage.py
    confirmations: int
