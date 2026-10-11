from collections.abc import Callable
from functools import lru_cache

from fastapi import Depends, Header, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.ai.base import LLMProvider
from app.ai.factory import LazyLLMProvider
from app.auth.security import decode_access_token
from app.auth.service import AuthService
from app.conversation.engine import ConversationEngine
from app.conversation.service import ConversationService
from app.core.config import Settings, get_settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.database.session import get_session_factory
from app.models import User
from app.notifications.email import EmailSender, create_email_sender
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


# ---- auth ----
_bearer = HTTPBearer(auto_error=False)


def get_email_sender(settings: Settings = Depends(get_settings)) -> EmailSender:
    return create_email_sender(settings)


def get_auth_service(
    sessions: Callable[[], Session] = Depends(get_sessions),
    settings: Settings = Depends(get_settings),
    email: EmailSender = Depends(get_email_sender),
) -> AuthService:
    return AuthService(sessions, settings, email=email)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> User:
    if creds is None:
        raise UnauthorizedError("Authentication required")
    claims = decode_access_token(settings, creds.credentials)
    user = await auth.get_user(claims["sub"])
    if user is None or user.status != "active":
        raise UnauthorizedError("Authentication required")
    return user


def require_role(*roles: str) -> Callable[[User], User]:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError("You do not have access to this resource")
        return user

    return dependency


require_superadmin = require_role("superadmin")
require_admin_or_above = require_role("admin", "superadmin")
