import asyncio
import logging
from collections.abc import AsyncIterator, Callable

import jwt
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api import deps
from app.conversation.service import ConversationService
from app.core.config import Settings, get_settings
from app.core.errors import ConfigurationError, ForbiddenError, UnauthorizedError
from app.repositories.phone import business_for_number
from app.voice import phone, vapi

log = logging.getLogger(__name__)

router = APIRouter(tags=["vapi"])
WEBHOOK_PATH = "/api/vapi/webhook"
LLM_PATH = "/api/vapi/llm"
NOT_IN_SERVICE = "Sorry, this number is not in service. Goodbye."
APOLOGY = "I'm sorry, I had a problem just now. Could you say that again?"


@router.post(WEBHOOK_PATH)
async def webhook(
    request: Request,
    authorization: str | None = Header(None),
    x_vapi_secret: str | None = Header(None),
    settings: Settings = Depends(get_settings),
    sessions: Callable[[], Session] = Depends(deps.get_sessions),
    service: ConversationService = Depends(deps.get_service),
):
    """Vapi's server messages. `assistant-request` (a call came in) is answered with the dialled business's assistant;
    the other messages need no reply."""
    if not (settings.public_base_url and settings.vapi_webhook_secret):
        raise ConfigurationError("PUBLIC_BASE_URL and VAPI_WEBHOOK_SECRET must be set to take Vapi calls")
    if not vapi.valid_secret(settings.vapi_webhook_secret, authorization, x_vapi_secret):
        raise ForbiddenError("Invalid Vapi credential")

    message = (await request.json()).get("message") or {}
    kind = message.get("type")
    if kind not in ("assistant-request", "end-of-call-report"):
        return {}

    dialled_raw, caller_raw, call_id = vapi.call_numbers(message)
    dialled = phone.normalize_phone(dialled_raw)

    if kind == "end-of-call-report":
        ended = message.get("endedReason")
        if vapi.is_error_ending(ended):
            await _alert_dropped_call(sessions, service, dialled, phone.normalize_phone(caller_raw), call_id, str(ended))
        return {}

    def lookup():
        with sessions() as session:
            found = business_for_number(session, dialled) if dialled else None
            return found[0].id if found else None

    tenant_id = await asyncio.to_thread(lookup)
    if tenant_id is None:
        log.info("vapi call to a number that is not in service")
        return {"error": NOT_IN_SERVICE}

    conversation_id, _greeting = await service.start(tenant_id)
    profile = await service.get_profile(tenant_id, conversation_id)
    await service.update_context(
        tenant_id,
        conversation_id,
        {"channel": "phone", "call_id": call_id, "caller": {"phone": phone.normalize_phone(caller_raw)}},
    )
    token = vapi.create_llm_token(settings, tenant_id, conversation_id)
    llm_url = f"{settings.public_base_url.rstrip('/')}{LLM_PATH}/{token}"
    return {"assistant": vapi.assistant_config(settings, profile, llm_url)}


async def _alert_dropped_call(sessions, service: ConversationService, dialled, caller, call_id, ended: str) -> None:
    def lookup():
        with sessions() as session:
            found = business_for_number(session, dialled) if dialled else None
            return found[0].id if found else None

    tenant_id = await asyncio.to_thread(lookup)
    if tenant_id is None:
        log.warning("a call to a number that is not in service ended with %s", ended)
        return
    try:
        await service.alert_call_ended(tenant_id, call_id, caller, ended)
    except Exception:
        log.exception("could not alert the business about a dropped call", extra={"tenant_id": tenant_id})


@router.post(LLM_PATH + "/{token}/chat/completions")
async def chat_completions(
    token: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    service: ConversationService = Depends(deps.get_service),
):
    """Vapi's custom-LLM endpoint: one call per caller turn. Streams the assistant's reply as chat-completion chunks."""
    try:
        claims = vapi.read_llm_token(settings, token)
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid or expired call token") from exc
    tenant_id, conversation_id = claims["tid"], claims["cid"]
    user_text = vapi.last_user_text((await request.json()).get("messages") or [])

    async def stream() -> AsyncIterator[str]:
        try:
            if user_text:
                async for delta in service.reply_stream(tenant_id, conversation_id, user_text):
                    yield vapi.sse_chunk(delta)
        except Exception:
            log.exception("vapi turn failed", extra={"tenant_id": tenant_id, "session_id": conversation_id})
            yield vapi.sse_chunk(APOLOGY)
        yield vapi.sse_chunk(finish=True)
        yield vapi.SSE_DONE

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
