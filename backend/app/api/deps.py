from collections.abc import Callable
from functools import lru_cache

from fastapi import Depends, Header, WebSocket
from sqlalchemy.orm import Session

from app.ai.base import LLMProvider
from app.ai.factory import LazyLLMProvider
from app.conversation.engine import ConversationEngine
from app.conversation.service import ConversationService
from app.core.config import Settings, get_settings
from app.database.session import get_session_factory
from app.tools.registry import ToolRegistry
from app.voice.base import BrowserVoiceProvider, STTProvider, TTSProvider, VoiceProvider
from app.voice.deepgram import DeepgramSTT, DeepgramTTS

# Every dependency below is overridable in tests via app.dependency_overrides.


def get_tenant_id(
    x_tenant_id: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> str:
    # Phase 1: tenant comes from a header (default demo tenant). Phase 8 replaces this with JWT claims.
    return x_tenant_id or settings.default_tenant_id


def get_sessions() -> Callable[[], Session]:
    return get_session_factory()


@lru_cache
def _llm(provider: str) -> LLMProvider:  # cached per provider name; settings are process-wide
    return LazyLLMProvider(get_settings())


def get_llm() -> LLMProvider:
    return _llm(get_settings().llm_provider)


def get_tool_registry() -> ToolRegistry:
    return ToolRegistry()  # domain tools are registered here from Phase 2/3


def get_stt(settings: Settings = Depends(get_settings)) -> STTProvider:
    return DeepgramSTT(settings.deepgram_api_key, settings.deepgram_stt_model)


def get_tts(settings: Settings = Depends(get_settings)) -> TTSProvider:
    return DeepgramTTS(settings.deepgram_api_key, settings.deepgram_tts_model)


def get_voice_provider(tts: TTSProvider = Depends(get_tts)) -> VoiceProvider:
    return BrowserVoiceProvider(tts)


def get_service(
    sessions: Callable[[], Session] = Depends(get_sessions),
    llm: LLMProvider = Depends(get_llm),
    tools: ToolRegistry = Depends(get_tool_registry),
) -> ConversationService:
    return ConversationService(sessions, ConversationEngine(llm, tools))


# WebSocket routes cannot use Header()/Depends on every parameter the same way; resolve manually.
def ws_tenant_id(ws: WebSocket) -> str:
    return ws.query_params.get("tenantId") or get_settings().default_tenant_id
