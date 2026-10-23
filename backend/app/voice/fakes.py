import asyncio
from collections.abc import AsyncIterator

from app.voice.base import STTProvider, STTSession, TranscriptEvent, TTSProvider


class FakeSTTSession(STTSession):
    """Treats every audio chunk as UTF-8 text and emits it as a final utterance (test double)."""

    def __init__(self):
        self._queue: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()

    async def send_audio(self, data: bytes) -> None:
        self._queue.put_nowait(TranscriptEvent(data.decode("utf-8"), True))

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while (event := await self._queue.get()) is not None:
            yield event

    async def close(self) -> None:
        self._queue.put_nowait(None)


class FakeSTT(STTProvider):
    async def open(self, language: str, telephony: bool = False) -> STTSession:
        return FakeSTTSession()


class FakeTTS(TTSProvider):
    mime_type = "audio/mpeg"

    def __init__(self):
        self.spoken: list[str] = []

    async def synthesize(self, text: str, telephony: bool = False) -> bytes:
        self.spoken.append(text)
        return f"AUDIO:{text}".encode()
