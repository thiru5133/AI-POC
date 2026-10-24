"""Phone calls through Vapi, with this server as the brain.

Vapi owns the telephone line, speech-to-text, speech-to-voice and barge-in. We stay in charge of what is said:
1. Vapi POSTs an `assistant-request` to /api/vapi/webhook when someone dials a business's number. We find the business
   from the dialled number and answer with an assistant whose language model is a "custom LLM" URL on this server.
2. Every turn Vapi POSTs the conversation to that URL and plays whatever we stream back (OpenAI chat-completion SSE).

The LLM URL has no login, so it carries a signed token naming the business and conversation (like the Twilio stream).
"""

import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.conversation.context import CALL_CLOSING
from app.core.config import Settings
from app.domain.profile import DomainProfile

TOKEN_AUDIENCE = "vapi-llm"
MODEL_NAME = "receptionist"


# ---------- who is calling us ----------
def valid_secret(expected: str, authorization: str | None, x_vapi_secret: str | None) -> bool:
    """Vapi sends the server credential as `Authorization: Bearer <secret>` or, for the legacy setup, `X-Vapi-Secret`."""
    if not expected:
        return False
    sent = x_vapi_secret or ""
    if authorization and authorization.lower().startswith("bearer "):
        sent = authorization[7:].strip()
    return hmac.compare_digest(sent.encode(), expected.encode())


# ---------- the signed link between the webhook and the LLM URL ----------
def create_llm_token(settings: Settings, tenant_id: str, conversation_id: str) -> str:
    claims = {
        "aud": TOKEN_AUDIENCE,
        "tid": tenant_id,
        "cid": conversation_id,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=settings.vapi_llm_token_seconds),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def read_llm_token(settings: Settings, token: str) -> dict:
    """The claims of a valid, unexpired token; raises jwt.PyJWTError otherwise. Never accepted as a login or stream token."""
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], audience=TOKEN_AUDIENCE)


# ---------- the webhook ----------
def call_numbers(message: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """(dialled number, caller number, Vapi call id) from a server message. Vapi puts the dialled number and the caller
    on the message itself; `call.phoneNumber` is empty for an assistant-request, so it is only a fallback."""
    call = message.get("call") or {}
    dialled = (message.get("phoneNumber") or call.get("phoneNumber") or {}).get("number")
    caller = (message.get("customer") or call.get("customer") or {}).get("number")
    return dialled, caller, call.get("id")


def is_error_ending(reason: str | None) -> bool:
    """Whether Vapi ended the call because something broke (not because someone hung up or the caller went silent):
    reasons such as `pipeline-error-openai-llm-failed` or `assistant-request-returned-error`."""
    reason = (reason or "").lower()
    return "error" in reason or "failed" in reason


def voice_id(tts_model: str) -> str:
    """Deepgram's Vapi voice id from a model name: 'aura-asteria-en' -> 'asteria'."""
    parts = tts_model.split("-")
    return parts[1] if len(parts) >= 3 and parts[0] == "aura" else tts_model


def assistant_config(settings: Settings, profile: DomainProfile, llm_url: str) -> dict[str, Any]:
    identity = profile.identity
    return {
        "name": identity.organization_name[:40],
        "firstMessage": identity.greeting,
        "model": {"provider": "custom-llm", "url": llm_url, "model": MODEL_NAME},
        "transcriber": {"provider": "deepgram", "model": settings.deepgram_stt_model, "language": identity.language},
        "voice": {"provider": "deepgram", "voiceId": voice_id(settings.deepgram_tts_model)},
        "serverMessages": ["end-of-call-report"],
        "endCallPhrases": [CALL_CLOSING],  # hang up once a booking is confirmed, so the call stops being billed
    }


# ---------- the custom LLM endpoint ----------
def last_user_text(messages: list[dict[str, Any]]) -> str:
    """What the caller just said: the content of the newest user message (Vapi resends the whole transcript)."""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, list):  # content parts: [{"type": "text", "text": "..."}]
            content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
        return (content or "").strip()
    return ""


def sse_chunk(text: str | None = None, finish: bool = False, completion_id: str = "chatcmpl-receptionist") -> str:
    delta: dict[str, Any] = {} if finish else {"role": "assistant", "content": text or ""}
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL_NAME,
        "choices": [{"index": 0, "delta": delta, "finish_reason": "stop" if finish else None}],
    }
    return f"data: {json.dumps(chunk)}\n\n"


SSE_DONE = "data: [DONE]\n\n"
