from collections.abc import Callable

from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy.orm import Session

from app.api import deps
from app.api.schemas import (
    AudioInfo,
    ConversationOut,
    CreateConversationRequest,
    CreateConversationResponse,
    DomainProfileOut,
    SendMessageRequest,
    SendMessageResponse,
    VoiceSessionRequest,
    VoiceSessionResponse,
)
from app.conversation.service import ConversationService
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.repositories.conversations import DomainProfileRepository
from app.voice.base import STTProvider, TTSProvider, VoiceProvider
from app.voice.session import VoiceSession

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/api/conversations", response_model=CreateConversationResponse)
async def create_conversation(
    body: CreateConversationRequest,
    tenant_id: str = Depends(deps.get_tenant_id),
    settings: Settings = Depends(get_settings),
    service: ConversationService = Depends(deps.get_service),
):
    conv_id, greeting = await service.start(
        body.tenant_id or tenant_id, body.domain_profile_id or settings.default_domain_profile_id
    )
    return CreateConversationResponse(id=conv_id, greeting=greeting)


@router.post("/api/conversations/{conversation_id}/messages", response_model=SendMessageResponse)
async def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    tenant_id: str = Depends(deps.get_tenant_id),
    service: ConversationService = Depends(deps.get_service),
):
    reply = await service.reply(tenant_id, conversation_id, body.text)
    return SendMessageResponse(reply=reply)


@router.get("/api/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: str,
    tenant_id: str = Depends(deps.get_tenant_id),
    service: ConversationService = Depends(deps.get_service),
):
    return await service.get(tenant_id, conversation_id)


@router.post("/api/voice/session", response_model=VoiceSessionResponse)
async def create_voice_session(
    body: VoiceSessionRequest,
    tenant_id: str = Depends(deps.get_tenant_id),
    service: ConversationService = Depends(deps.get_service),
    provider: VoiceProvider = Depends(deps.get_voice_provider),
):
    await service.get(tenant_id, body.conversation_id)  # 404 if missing / other tenant
    info = provider.create_session(body.conversation_id)
    return VoiceSessionResponse(
        conversation_id=info.conversation_id,
        transport=info.transport,
        ws_path=info.ws_path,
        audio=AudioInfo(mime_type=info.audio_mime_type),
    )


@router.get("/api/domain-profiles/{profile_id}", response_model=DomainProfileOut)
async def get_domain_profile(
    profile_id: str,
    tenant_id: str = Depends(deps.get_tenant_id),
    sessions: Callable[[], Session] = Depends(deps.get_sessions),
):
    with sessions() as session:
        row = DomainProfileRepository(session, tenant_id).get(profile_id)
        if row is None:
            raise NotFoundError("Domain profile not found")
        return DomainProfileOut(id=row.id, name=row.name, domain_type=row.domain_type, config=row.config)


@router.websocket("/ws/voice/{conversation_id}")
async def voice_socket(
    websocket: WebSocket,
    conversation_id: str,
    service: ConversationService = Depends(deps.get_service),
    stt: STTProvider = Depends(deps.get_stt),
    tts: TTSProvider = Depends(deps.get_tts),
):
    await VoiceSession(
        websocket, service, stt, tts, deps.ws_tenant_id(websocket), conversation_id
    ).run()
