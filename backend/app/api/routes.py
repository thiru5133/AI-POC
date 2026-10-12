from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, WebSocket
from sqlalchemy.orm import Session

from app.api import deps
from app.api.schemas import (
    AudioInfo,
    ConversationList,
    ConversationOut,
    CreateConversationResponse,
    DomainProfileOut,
    SendMessageRequest,
    SendMessageResponse,
    VoiceSessionRequest,
    VoiceSessionResponse,
)
from app.conversation.service import ConversationService
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
    scope: deps.ChatScope = Depends(deps.get_chat_scope),
    service: ConversationService = Depends(deps.get_service),
):
    conv_id, greeting = await service.start(scope.tenant_id, scope.user_id)
    return CreateConversationResponse(id=conv_id, greeting=greeting)


@router.post("/api/conversations/{conversation_id}/messages", response_model=SendMessageResponse)
async def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    scope: deps.ChatScope = Depends(deps.get_chat_scope),
    service: ConversationService = Depends(deps.get_service),
):
    reply = await service.reply(scope.tenant_id, conversation_id, body.text, scope.user_id)
    return SendMessageResponse(reply=reply)


@router.get("/api/conversations", response_model=ConversationList)
async def list_conversations(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_empty: bool = Query(False, alias="includeEmpty"),
    scope: deps.ChatScope = Depends(deps.get_chat_scope),
    service: ConversationService = Depends(deps.get_service),
):
    """A business admin sees all of their business's conversations; a customer only their own."""
    return await service.list(scope.tenant_id, limit, offset, include_empty, scope.user_id)


@router.get("/api/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: str,
    scope: deps.ChatScope = Depends(deps.get_chat_scope),
    service: ConversationService = Depends(deps.get_service),
):
    return await service.get(scope.tenant_id, conversation_id, scope.user_id)


@router.post("/api/voice/session", response_model=VoiceSessionResponse)
async def create_voice_session(
    body: VoiceSessionRequest,
    scope: deps.ChatScope = Depends(deps.get_chat_scope),
    service: ConversationService = Depends(deps.get_service),
    provider: VoiceProvider = Depends(deps.get_voice_provider),
):
    await service.get(scope.tenant_id, body.conversation_id, scope.user_id)  # 404 if missing / other tenant
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
    scope: deps.ChatScope = Depends(deps.get_chat_scope),
    sessions: Callable[[], Session] = Depends(deps.get_sessions),
):
    with sessions() as session:
        row = DomainProfileRepository(session, scope.tenant_id).get(profile_id)
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
    scope: deps.ChatScope = Depends(deps.get_ws_chat_scope),
):
    await VoiceSession(websocket, service, stt, tts, scope.tenant_id, conversation_id, scope.user_id).run()
