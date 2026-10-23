"""Real phone calls through Twilio Programmable Voice.

A call reaches the assistant in two steps:
1. Twilio POSTs to /api/phone/incoming when someone dials a business's number. The reply is TwiML that tells Twilio to
   open a Media Stream (a WebSocket carrying the call's audio) to /ws/phone.
2. PhoneSession drives that stream exactly like the browser's VoiceSession does, with phone-line audio (8 kHz mu-law).

The stream has no login, so the webhook hands it a short-lived signed token naming the business and conversation.
"""

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape, quoteattr

import httpx
import jwt
from fastapi import WebSocket

from app.core.config import Settings
from app.core.errors import ConfigurationError, UpstreamError
from app.conversation.service import ConversationService
from app.voice.base import STTProvider, TTSProvider
from app.voice.session import VoiceSession

log = logging.getLogger(__name__)

TOKEN_AUDIENCE = "phone-stream"
AUDIO_CHUNK_BYTES = 1600  # 200 ms of 8 kHz mu-law per outgoing frame
TRANSFER_WAIT_SECONDS = 15  # how long to let the caller hear the last words before the call is handed over
CALLS_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls/{call_sid}.json"
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(value: str | None) -> str | None:
    """`value` as E.164 (+ and 8-15 digits), or None when it is not a phone number (e.g. caller ID 'anonymous')."""
    if not value:
        return None
    number = re.sub(r"[\s\-().]", "", value)
    return number if _E164.match(number) else None


# ---------- Twilio request signature ----------
def twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """The X-Twilio-Signature Twilio would send: HMAC-SHA1 over the URL plus the sorted form fields."""
    data = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def valid_twilio_signature(auth_token: str, url: str, params: dict[str, str], signature: str) -> bool:
    return hmac.compare_digest(twilio_signature(auth_token, url, params), signature or "")


# ---------- the signed link between the webhook and the audio stream ----------
def create_stream_token(settings: Settings, tenant_id: str, conversation_id: str, transfer_to: str | None) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "aud": TOKEN_AUDIENCE,
        "tid": tenant_id,
        "cid": conversation_id,
        "xfer": transfer_to,
        "exp": now + timedelta(seconds=settings.phone_stream_token_seconds),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def read_stream_token(settings: Settings, token: str) -> dict:
    """The claims of a valid, unexpired stream token; raises jwt.PyJWTError otherwise. It is never accepted as a login
    token (different audience) and a login token is never accepted here."""
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], audience=TOKEN_AUDIENCE)


# ---------- TwiML ----------
def stream_twiml(stream_url: str, token: str) -> str:
    return (
        f"<Response><Connect><Stream url={quoteattr(stream_url)}>"
        f"<Parameter name=\"token\" value={quoteattr(token)}/></Stream></Connect></Response>"
    )


def message_twiml(message: str) -> str:
    return f"<Response><Say>{escape(message)}</Say><Hangup/></Response>"


# ---------- taking over a live call ----------
class CallControl(ABC):
    @abstractmethod
    def transfer(self, call_sid: str, to: str) -> None:
        """Blocking: hands the live call to the phone number `to`. Raises UpstreamError when that fails."""


class TwilioCallControl(CallControl):
    def __init__(self, settings: Settings):
        self._s = settings

    def transfer(self, call_sid: str, to: str) -> None:
        if not (self._s.twilio_account_sid and self._s.twilio_auth_token):
            raise ConfigurationError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are not set")
        try:
            resp = httpx.post(
                CALLS_URL.format(sid=self._s.twilio_account_sid, call_sid=call_sid),
                data={"Twiml": f"<Response><Dial>{escape(to)}</Dial></Response>"},
                auth=(self._s.twilio_account_sid, self._s.twilio_auth_token),
                timeout=15,
            )
        except httpx.HTTPError as exc:
            log.error("twilio transfer request failed: %s", type(exc).__name__)
            raise UpstreamError("Could not transfer the call: Twilio could not be reached.") from exc
        if resp.status_code not in (200, 201):
            log.error("twilio rejected the transfer: %s %s", resp.status_code, resp.text[:300])
            raise UpstreamError(f"Could not transfer the call: Twilio returned an error ({resp.status_code}).")


def create_call_control(settings: Settings) -> CallControl:
    return TwilioCallControl(settings)


# ---------- the call itself ----------
class PhoneSession(VoiceSession):
    """One phone call over a Twilio Media Stream. Twilio sends JSON events (connected, start, media, mark, stop) with
    base64 mu-law audio; the assistant's speech goes back as `media` events."""

    telephony = True

    def __init__(
        self,
        ws: WebSocket,
        service: ConversationService,
        stt: STTProvider,
        tts: TTSProvider,
        settings: Settings,
        call_control: CallControl,
    ):
        super().__init__(ws, service, stt, tts, tenant_id="", conversation_id="", user_id=None)
        self._settings = settings
        self._call_control = call_control
        self._stream_sid = ""
        self._call_sid = ""
        self._transfer_to: str | None = None
        self._transferred = False
        self._mark_played = asyncio.Event()

    async def _handshake(self) -> bool:
        """Waits for Twilio's `start` event and accepts the call only when its token checks out."""
        try:
            while True:
                event = json.loads(await asyncio.wait_for(self.ws.receive_text(), timeout=10))
                if event.get("event") == "start":
                    break
                if event.get("event") == "stop":
                    return False
            start = event["start"]
            claims = read_stream_token(self._settings, start["customParameters"]["token"])
        except Exception as exc:  # no/odd start event, bad or expired token, disconnect
            log.warning("phone stream refused: %s", type(exc).__name__)
            with contextlib.suppress(Exception):
                await self.ws.close(code=1008)
            return False
        self._stream_sid = start["streamSid"]
        self._call_sid = start.get("callSid", "")
        self.tenant_id, self.conversation_id = claims["tid"], claims["cid"]
        self._transfer_to = claims.get("xfer")
        self._log_extra = {"tenant_id": self.tenant_id, "session_id": self.conversation_id}
        return True

    async def _receive(self, stt) -> None:
        while True:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if not msg.get("text"):
                continue
            event = json.loads(msg["text"])
            kind = event.get("event")
            if kind == "media":
                await stt.send_audio(base64.b64decode(event["media"]["payload"]))
            elif kind == "mark":
                self._mark_played.set()
            elif kind == "stop":
                return

    async def _send(self, payload: dict) -> None:
        # The browser's events (transcripts, text) mean nothing to a phone line: only interruptions and errors matter.
        if payload["type"] == "assistant.interrupt":
            await self._clear_audio()
        elif payload["type"] == "error":
            log.warning("phone call error %s: %s", payload.get("code"), payload.get("message"), extra=self._log_extra)

    async def _send_audio(self, audio: bytes) -> None:
        for i in range(0, len(audio), AUDIO_CHUNK_BYTES):
            chunk = base64.b64encode(audio[i : i + AUDIO_CHUNK_BYTES]).decode()
            await self.ws.send_json({"event": "media", "streamSid": self._stream_sid, "media": {"payload": chunk}})

    async def _clear_audio(self) -> None:
        """Drops what Twilio has queued but not yet played (it plays faster than we generate)."""
        await self.ws.send_json({"event": "clear", "streamSid": self._stream_sid})

    async def _caller_started_talking(self) -> None:
        if self._speaking:
            await self._cancel_turn()
        await self._clear_audio()

    async def _after_turn(self) -> None:
        """When the assistant flagged that the caller needs a person, hand the call over once it has finished speaking."""
        if self._transferred or not self._transfer_to:
            return
        state = await self.service.get(self.tenant_id, self.conversation_id)
        if not state["context"].get("handoff_requested"):
            return
        self._transferred = True
        self._mark_played.clear()
        await self.ws.send_json({"event": "mark", "streamSid": self._stream_sid, "mark": {"name": "handoff"}})
        try:  # let the caller hear the last sentence before the line is handed over
            await asyncio.wait_for(self._mark_played.wait(), timeout=TRANSFER_WAIT_SECONDS)
        except asyncio.TimeoutError:
            pass
        try:
            await asyncio.to_thread(self._call_control.transfer, self._call_sid, self._transfer_to)
            log.info("call transferred to a person", extra=self._log_extra)
        except Exception as exc:
            log.error("call transfer failed: %s", exc, extra=self._log_extra)
            self._transferred = False
            self._transfer_to = None  # do not retry on every later turn
            await self._speak("I'm sorry, I couldn't connect you just now. Someone from the team will call you back.")
            await self._send({"type": "assistant.audio_end"})
