import asyncio
import json
import logging
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import httpx
import websockets.asyncio.client

from app.core.errors import ConfigurationError, UpstreamError
from app.voice.base import STTProvider, STTSession, TranscriptEvent, TTSProvider

log = logging.getLogger(__name__)


class DeepgramSTTSession(STTSession):
    def __init__(self, ws):
        self._ws = ws
        self._queue: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()
        self._pending: list[str] = []
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("type") == "UtteranceEnd":
                    self._flush()
                    continue
                if msg.get("type") != "Results":
                    continue
                text = msg["channel"]["alternatives"][0].get("transcript", "").strip()
                if not msg.get("is_final"):
                    if text:
                        self._queue.put_nowait(TranscriptEvent(" ".join([*self._pending, text]), False))
                    continue
                if text:
                    self._pending.append(text)
                    self._queue.put_nowait(TranscriptEvent(" ".join(self._pending), False))
                if msg.get("speech_final"):
                    self._flush()
        except Exception:
            log.exception("deepgram stt reader failed")
        finally:
            self._flush()
            self._queue.put_nowait(None)

    def _flush(self) -> None:
        if self._pending:
            self._queue.put_nowait(TranscriptEvent(" ".join(self._pending), True))
            self._pending = []

    async def send_audio(self, data: bytes) -> None:
        await self._ws.send(data)

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while (event := await self._queue.get()) is not None:
            yield event

    async def close(self) -> None:
        try:
            await self._ws.send(json.dumps({"type": "CloseStream"}))
            await self._ws.close()
        except Exception:
            pass
        self._reader.cancel()


class DeepgramSTT(STTProvider):
    def __init__(self, api_key: str, model: str):
        self._key = api_key
        self._model = model

    async def open(self, language: str) -> STTSession:
        if not self._key:
            raise ConfigurationError("DEEPGRAM_API_KEY is not set")
        params = urlencode(
            {
                "model": self._model,
                "language": language,
                "smart_format": "true",
                "interim_results": "true",
                "endpointing": 600,
                "utterance_end_ms": 1500,
            }
        )
        try:
            ws = await websockets.asyncio.client.connect(
                f"wss://api.deepgram.com/v1/listen?{params}",
                additional_headers={"Authorization": f"Token {self._key}"},
            )
        except Exception as exc:
            raise UpstreamError(f"Could not connect to Deepgram STT: {exc}") from exc
        return DeepgramSTTSession(ws)


class DeepgramTTS(TTSProvider):
    mime_type = "audio/mpeg"

    def __init__(self, api_key: str, model: str):
        self._key = api_key
        self._model = model

    async def synthesize(self, text: str) -> bytes:
        if not self._key:
            raise ConfigurationError("DEEPGRAM_API_KEY is not set")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.deepgram.com/v1/speak",
                params={"model": self._model, "encoding": "mp3"},
                headers={"Authorization": f"Token {self._key}"},
                json={"text": text},
            )
        if resp.status_code != 200:
            raise UpstreamError(f"Deepgram TTS failed ({resp.status_code}): {resp.text[:200]}")
        return resp.content
