"""Simulates a phone call from Twilio, so the whole phone path can be tested without ringing a phone.

    docker compose exec backend python -m app.voice.fake_call --number +17372508034 --say "Do you have a yoga class tomorrow?"

It does what Twilio does: POSTs a signed webhook for the dialled number, opens the audio stream with the token it gets back, and
"speaks" each --say sentence as phone-line audio (made with Deepgram text-to-speech). The assistant's greeting and answers are saved as
.wav files you can play, and the call's transcript is printed from the database. Nothing is sent to Twilio.
The business that owns the number must have saved it on the Phone page first.
"""

import argparse
import asyncio
import base64
import json
import re
import struct
import sys
import wave
from pathlib import Path
from urllib.parse import urlencode

import httpx
import websockets.asyncio.client

from app.core.config import Settings, get_settings
from app.voice.deepgram import DeepgramTTS
from app.voice.phone import normalize_phone, read_stream_token, twilio_signature

INCOMING_PATH = "/api/phone/incoming"
SAMPLE_RATE = 8000
FRAME_BYTES = 160  # 20 ms of 8 kHz mu-law
MULAW_SILENCE = b"\xff"
SILENCE_AFTER_SPEECH_SECONDS = 1.5  # lets speech-to-text decide the caller finished


def ulaw_to_pcm16(data: bytes) -> bytes:
    """G.711 mu-law to 16-bit little-endian PCM (what a .wav holds)."""
    out = bytearray()
    for byte in data:
        u = ~byte & 0xFF
        sample = (((u & 0x0F) << 3) + 0x84) << ((u & 0x70) >> 4)
        sample -= 0x84
        out += struct.pack("<h", -sample if u & 0x80 else sample)
    return bytes(out)


def save_wav(path: Path, mulaw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(ulaw_to_pcm16(mulaw))


def webhook_request(settings: Settings, number: str, caller: str, call_sid: str) -> tuple[str, dict[str, str]]:
    """(body, headers) of the signed POST Twilio would send; the signature covers the PUBLIC url, as Twilio's does."""
    form = {"To": number, "From": caller, "CallSid": call_sid}
    signature = twilio_signature(settings.twilio_auth_token, settings.public_base_url.rstrip("/") + INCOMING_PATH, form)
    return urlencode(form), {"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": signature}


def read_twiml(twiml: str) -> tuple[str | None, str | None]:
    """(stream token, spoken message). A call that is not answered by a stream carries a <Say> message instead."""
    token = re.search(r'name="token" value="([^"]+)"', twiml)
    say = re.search(r"<Say>(.*?)</Say>", twiml)
    return (token.group(1) if token else None), (say.group(1) if say else None)


async def listen(ws, first_frame_timeout: float, quiet_seconds: float) -> bytes:
    """Audio the assistant sends: waits for the first frame, then until it has been quiet for `quiet_seconds`."""
    audio = bytearray()
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=quiet_seconds if audio else first_frame_timeout)
        except asyncio.TimeoutError:
            return bytes(audio)
        event = json.loads(raw)
        if event.get("event") == "media":
            audio += base64.b64decode(event["media"]["payload"])
        elif event.get("event") == "mark":  # Twilio echoes a mark once the audio before it has played
            await ws.send(json.dumps({"event": "mark", "mark": event["mark"]}))


async def speak(ws, tts: DeepgramTTS, text: str) -> None:
    """Sends `text` as the caller's voice, in real time, followed by a moment of silence."""
    audio = await tts.synthesize(text, telephony=True)
    audio += MULAW_SILENCE * int(SILENCE_AFTER_SPEECH_SECONDS * SAMPLE_RATE)
    for i in range(0, len(audio), FRAME_BYTES):
        payload = base64.b64encode(audio[i : i + FRAME_BYTES]).decode()
        await ws.send(json.dumps({"event": "media", "media": {"track": "inbound", "payload": payload}}))
        await asyncio.sleep(FRAME_BYTES / SAMPLE_RATE)


def print_transcript(settings: Settings, token: str) -> None:
    from app.database.session import get_session_factory
    from app.repositories.conversations import ConversationRepository

    claims = read_stream_token(settings, token)
    with get_session_factory()() as session:
        messages = ConversationRepository(session, claims["tid"]).messages(claims["cid"])
        print("\nTranscript of the call:")
        for m in messages:
            print(f"  {'Caller   ' if m.role == 'user' else 'Assistant'}: {m.content}")
        conv = ConversationRepository(session, claims["tid"]).get(claims["cid"])
        context = conv.context or {}
        for key in ("urgency", "handoff_requested", "notifications_sent"):
            if context.get(key):
                print(f"  [{key} = {context[key]}]")


async def run(args: argparse.Namespace, settings: Settings) -> int:
    number, caller = normalize_phone(args.number), normalize_phone(args.caller)
    if not number or not caller:
        print("--number and --caller need a country code, for example +14155550100")
        return 2
    if not (settings.public_base_url and settings.twilio_auth_token):
        print("Set PUBLIC_BASE_URL and TWILIO_AUTH_TOKEN in .env first (the webhook is signed with them).")
        return 1
    if args.say and not settings.deepgram_api_key:
        print("DEEPGRAM_API_KEY is not set: it is needed to turn what you --say into audio.")
        return 1

    body, headers = webhook_request(settings, number, caller, "CAfakecall0000000000000000000000000")
    resp = httpx.post(args.server.rstrip("/") + INCOMING_PATH, content=body, headers=headers, timeout=30)
    print(f"Webhook answered {resp.status_code}")
    if resp.status_code != 200:
        print(resp.text[:300])
        return 1
    token, message = read_twiml(resp.text)
    if token is None:
        print(f"Twilio would have told the caller: {message!r}")
        print("-> No business has saved this number. Log in as the business admin, open the Phone page, save it, and run again.")
        return 1

    out = Path(args.out)
    ws_url = args.server.rstrip("/").replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws/phone"
    tts = DeepgramTTS(settings.deepgram_api_key, settings.deepgram_tts_model)
    async with websockets.asyncio.client.connect(ws_url) as ws:
        await ws.send(json.dumps({"event": "connected"}))
        await ws.send(json.dumps({
            "event": "start", "streamSid": "MZfake", "start": {"streamSid": "MZfake", "callSid": "CAfake", "customParameters": {"token": token}},
        }))
        greeting = await listen(ws, first_frame_timeout=20, quiet_seconds=2.5)
        save_wav(out / "1-greeting.wav", greeting)
        print(f"Assistant greeting: {len(greeting) / SAMPLE_RATE:.1f}s of audio -> {out / '1-greeting.wav'}")
        for n, sentence in enumerate(args.say, start=2):
            print(f"Caller says: {sentence!r}")
            await speak(ws, tts, sentence)
            reply = await listen(ws, first_frame_timeout=30, quiet_seconds=3)
            save_wav(out / f"{n}-reply.wav", reply)
            print(f"Assistant replied: {len(reply) / SAMPLE_RATE:.1f}s of audio -> {out / f'{n}-reply.wav'}")
        await ws.send(json.dumps({"event": "stop"}))
    print_transcript(settings, token)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--number", required=True, help="the business's phone number (the one saved on its Phone page)")
    parser.add_argument("--caller", default="+916383135741", help="the caller's number (caller ID)")
    parser.add_argument("--say", action="append", default=[], help="a sentence the caller says; repeat for several turns")
    parser.add_argument("--server", default="http://localhost:8000", help="where this backend listens, from where you run this")
    parser.add_argument("--out", default="fake_call_out", help="folder for the .wav files")
    args = parser.parse_args(argv)
    return asyncio.run(run(args, get_settings()))


if __name__ == "__main__":
    sys.exit(main())
