from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CreateConversationRequest(CamelModel):
    tenant_id: str | None = None
    domain_profile_id: str | None = None


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


class ConversationOut(CamelModel):
    id: str
    domain_profile_id: str
    status: str
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
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    organization_name: str = Field(min_length=1, max_length=200)

    @field_validator("organization_name")
    @classmethod
    def _org_name_not_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Organization name is required")
        return value

    @field_validator("name")
    @classmethod
    def _name_is_usable_as_login(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Name is required")
        if "@" in value:
            raise ValueError("Name cannot contain '@'")  # names double as login identifiers
        return value


class RegisterResponse(CamelModel):
    status: str = "pending"


class LoginRequest(CamelModel):
    identifier: str = Field(min_length=1, max_length=320)  # email or name
    password: str = Field(min_length=1, max_length=128)


class UserOut(CamelModel):
    id: str
    name: str
    email: str
    role: str
    status: str
    tenant_id: str | None = None


class LoginResponse(CamelModel):
    access_token: str
    user: UserOut


class OnboardingRequestOut(CamelModel):
    id: str
    name: str
    email: str
    status: str
    rejection_reason: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None


class RejectRequest(CamelModel):
    reason: str | None = Field(default=None, max_length=500)


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
    rejection_reason: str | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
