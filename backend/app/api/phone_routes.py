import asyncio
import logging
from collections.abc import Callable
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Request, WebSocket
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api import deps
from app.api.schemas import PhoneOut, PhoneUpdate
from app.api.vapi_routes import WEBHOOK_PATH
from app.conversation.service import ConversationService
from app.core.config import Settings, get_settings
from app.core.errors import ConfigurationError, ConflictError, ForbiddenError
from app.domain.hours import open_now
from app.models import User
from app.repositories.phone import PhoneRepository, business_for_number, domain_line_for
from app.voice import phone
from app.voice.base import STTProvider, TTSProvider

log = logging.getLogger(__name__)

router = APIRouter(tags=["phone"])
INCOMING_PATH = "/api/phone/incoming"
STREAM_PATH = "/ws/phone"


def _public_base(settings: Settings) -> str:
    return settings.public_base_url.rstrip("/")


def _provider(settings: Settings) -> str:
    """Vapi when the server has a Vapi webhook secret, otherwise the Twilio media stream."""
    return "vapi" if settings.vapi_webhook_secret else "twilio"


def _ready(settings: Settings) -> bool:
    if _provider(settings) == "vapi":
        return bool(settings.public_base_url)
    return bool(settings.public_base_url and settings.twilio_auth_token and settings.twilio_account_sid)


def _twiml(body: str) -> Response:
    return Response(content=body, media_type="text/xml")


# ---------- Twilio -> us ----------
@router.post(INCOMING_PATH)
async def incoming_call(
    request: Request,
    settings: Settings = Depends(get_settings),
    sessions: Callable[[], Session] = Depends(deps.get_sessions),
    service: ConversationService = Depends(deps.get_service),
):
    """Twilio's 'a call comes in' webhook. Answers with TwiML that opens the audio stream to this server."""
    if not (settings.public_base_url and settings.twilio_auth_token):
        raise ConfigurationError("PUBLIC_BASE_URL and TWILIO_AUTH_TOKEN must be set to take phone calls")
    form = dict(parse_qsl((await request.body()).decode(), keep_blank_values=True))
    signature = request.headers.get("X-Twilio-Signature", "")
    if not phone.valid_twilio_signature(settings.twilio_auth_token, _public_base(settings) + INCOMING_PATH, form, signature):
        raise ForbiddenError("Invalid Twilio signature")

    dialled = phone.normalize_phone(form.get("To"))

    def lookup():
        with sessions() as session:
            found = business_for_number(session, dialled) if dialled else None
            return (found[0].id, found[1].transfer_number) if found else None

    found = await asyncio.to_thread(lookup)
    if found is None:
        log.info("call to a number that is not in service")
        return _twiml(phone.message_twiml("Sorry, this number is not in service. Goodbye."))
    tenant_id, transfer_number = found

    conversation_id, _greeting = await service.start(tenant_id)
    profile = await service.get_profile(tenant_id, conversation_id)
    # A call can only be handed to a person while the business is open: otherwise nobody would pick up.
    transfer_to = transfer_number if transfer_number and open_now(profile.identity.hours, profile.identity.timezone) else None
    await service.update_context(
        tenant_id,
        conversation_id,
        {
            "channel": "phone",
            "call_sid": form.get("CallSid"),
            "transfer_available": transfer_to is not None,
            "caller": {"phone": phone.normalize_phone(form.get("From"))},
        },
    )
    token = phone.create_stream_token(settings, tenant_id, conversation_id, transfer_to)
    stream_url = _public_base(settings).replace("https://", "wss://", 1).replace("http://", "ws://", 1) + STREAM_PATH
    return _twiml(phone.stream_twiml(stream_url, token))


@router.websocket(STREAM_PATH)
async def phone_stream(
    websocket: WebSocket,
    service: ConversationService = Depends(deps.get_service),
    stt: STTProvider = Depends(deps.get_stt),
    tts: TTSProvider = Depends(deps.get_tts),
    settings: Settings = Depends(get_settings),
    call_control: phone.CallControl = Depends(deps.get_call_control),
):
    await phone.PhoneSession(websocket, service, stt, tts, settings, call_control).run()


# ---------- the business's own phone settings ----------
def _out(
    settings: Settings, tenant_id: str, number: str | None, transfer: str | None, domain_line: tuple[str, str | None] | None = None
) -> PhoneOut:
    provider = _provider(settings)
    path = WEBHOOK_PATH if provider == "vapi" else INCOMING_PATH
    return PhoneOut(
        number=number,
        transfer_number=transfer,
        domain_name=domain_line[0] if domain_line else None,
        domain_number=domain_line[1] if domain_line else None,
        provider=provider,
        webhook_url=_public_base(settings) + path if settings.public_base_url else None,
        public_url=f"{settings.app_base_url.rstrip('/')}/call/{tenant_id}" if number else None,
        ready=_ready(settings),
    )


@router.get("/api/org/phone", response_model=PhoneOut)
async def get_phone(
    user: User = Depends(deps.require_admin),
    settings: Settings = Depends(get_settings),
    sessions: Callable[[], Session] = Depends(deps.get_sessions),
):
    tenant_id = deps.require_tenant(user)
    with sessions() as session:
        row = PhoneRepository(session, tenant_id).get_for_tenant()
        return _out(
            settings, tenant_id, row.number if row else None, row.transfer_number if row else None, domain_line_for(session, tenant_id)
        )


@router.put("/api/org/phone", response_model=PhoneOut)
async def put_phone(
    body: PhoneUpdate,
    user: User = Depends(deps.require_admin),
    settings: Settings = Depends(get_settings),
    sessions: Callable[[], Session] = Depends(deps.get_sessions),
):
    tenant_id = deps.require_tenant(user)
    with sessions() as session:
        repo = PhoneRepository(session, tenant_id)
        if body.number is None:
            repo.clear()
            session.commit()
            return _out(settings, tenant_id, None, None, domain_line_for(session, tenant_id))
        if body.transfer_number == body.number:
            raise ConflictError("The transfer number must be different from the business number", "transfer_loop")
        if repo.number_taken(body.number):
            raise ConflictError("That number is already used by another business", "number_taken")
        row = repo.save(body.number, body.transfer_number)
        session.commit()
        return _out(settings, tenant_id, row.number, row.transfer_number, domain_line_for(session, tenant_id))
