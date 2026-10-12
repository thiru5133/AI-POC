from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, Header, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.ai.base import LLMProvider
from app.ai.factory import LazyLLMProvider
from app.auth.security import decode_access_token
from app.auth.service import AuthService
from app.conversation.engine import ConversationEngine
from app.conversation.service import ConversationService
from app.core.config import Settings, get_settings
from app.mcp.client import McpClient, SdkMcpClient
from app.mcp.federation import ResultCache
from app.mcp.service import McpConfigService
from app.mcp.tools import McpToolSource, ToolListCache
from app.core.errors import ForbiddenError, UnauthorizedError
from app.database.session import get_session_factory
from app.models import User
from app.notifications.email import EmailSender, create_email_sender
from app.tenants.service import BusinessService
from app.tools.registry import ToolRegistry
from app.voice.base import BrowserVoiceProvider, STTProvider, TTSProvider, VoiceProvider
from app.voice.deepgram import DeepgramSTT, DeepgramTTS

# Every dependency below is overridable in tests via app.dependency_overrides.


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


_mcp_tool_cache = ToolListCache()
_mcp_result_cache = ResultCache()


def get_mcp_client(settings: Settings = Depends(get_settings)) -> McpClient:
    return SdkMcpClient()


def get_mcp_config(
    sessions: Callable[[], Session] = Depends(get_sessions),
    settings: Settings = Depends(get_settings),
    client: McpClient = Depends(get_mcp_client),
) -> McpConfigService:
    return McpConfigService(sessions, settings, client)


def get_service(
    sessions: Callable[[], Session] = Depends(get_sessions),
    settings: Settings = Depends(get_settings),
    llm: LLMProvider = Depends(get_llm),
    tools: ToolRegistry = Depends(get_tool_registry),
    mcp_client: McpClient = Depends(get_mcp_client),
) -> ConversationService:
    mcp = McpToolSource(sessions, settings, mcp_client, _mcp_tool_cache, _mcp_result_cache)
    return ConversationService(sessions, ConversationEngine(llm, tools, mcp=mcp))


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


def get_business_service(
    sessions: Callable[[], Session] = Depends(get_sessions),
    settings: Settings = Depends(get_settings),
    email: EmailSender = Depends(get_email_sender),
) -> BusinessService:
    return BusinessService(sessions, settings, email=email)


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
require_admin = require_role("admin")


def require_tenant(user: User) -> str:
    """The organization an admin acts for. Always taken from the authenticated user, never from the request."""
    if not user.tenant_id:
        raise ForbiddenError("Your account does not belong to an organization")
    return user.tenant_id


# ---- who is chatting, and for which business ----
@dataclass(frozen=True)
class ChatScope:
    """`tenant_id` is the business the conversation belongs to. `user_id` is set for customers, who are limited to
    their own conversations; a business's admin (user_id None) sees all of that business's conversations."""

    tenant_id: str
    user_id: str | None = None


async def _scope_for(user: User, business_id: str | None, auth: AuthService) -> ChatScope:
    if user.role == "admin":
        return ChatScope(require_tenant(user))  # an admin always acts for their own business
    if user.role == "user":
        # Customers pick the business they are talking to; it must exist and be active.
        if not business_id or not await auth.is_active_business(business_id):
            raise ForbiddenError("Choose a business to talk to", "business_required")
        return ChatScope(business_id, user.id)
    raise ForbiddenError("Superadmins manage businesses and do not take part in conversations")


async def get_chat_scope(
    user: User = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
    business_id: str | None = Header(default=None, alias="X-Business-Id"),
) -> ChatScope:
    return await _scope_for(user, business_id, auth)


async def get_ws_chat_scope(
    websocket: WebSocket,
    auth: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> ChatScope:
    # Browsers cannot set headers on a WebSocket, so the token (and a customer's business) travel in the query string.
    # An AppError cannot be answered with an HTTP envelope during a WebSocket handshake: reject explicitly.
    token = websocket.query_params.get("token")
    try:
        if not token:
            raise UnauthorizedError("Authentication required")
        claims = decode_access_token(settings, token)
        user = await auth.get_user(claims["sub"])
        if user is None or user.status != "active":
            raise UnauthorizedError("Authentication required")
        return await _scope_for(user, websocket.query_params.get("business"), auth)
    except (UnauthorizedError, ForbiddenError):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION) from None
