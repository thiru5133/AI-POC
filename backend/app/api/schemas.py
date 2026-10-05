from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
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
