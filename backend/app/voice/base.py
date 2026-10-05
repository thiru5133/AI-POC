from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class TranscriptEvent:
    text: str
    is_final: bool  # True = a complete utterance ready to be answered


class STTSession(ABC):
    @abstractmethod
    async def send_audio(self, data: bytes) -> None: ...

    @abstractmethod
    def events(self) -> AsyncIterator[TranscriptEvent]: ...

    @abstractmethod
    async def close(self) -> None: ...


class STTProvider(ABC):
    @abstractmethod
    async def open(self, language: str) -> STTSession: ...


class TTSProvider(ABC):
    mime_type: str = "audio/mpeg"

    @abstractmethod
    async def synthesize(self, text: str) -> bytes: ...


@dataclass
class VoiceSessionInfo:
    conversation_id: str
    transport: str  # "websocket" now; "vapi" / "twilio" later
    ws_path: str | None
    audio_mime_type: str


class VoiceProvider(ABC):
    """Transport-level provider. The Conversation Engine only ever sees text turns, so a new provider
    (Vapi, Twilio, ...) is a new VoiceProvider + its own session driver — the engine is untouched."""

    name: str

    @abstractmethod
    def create_session(self, conversation_id: str) -> VoiceSessionInfo: ...


class BrowserVoiceProvider(VoiceProvider):
    name = "browser"

    def __init__(self, tts: TTSProvider):
        self._tts = tts

    def create_session(self, conversation_id: str) -> VoiceSessionInfo:
        return VoiceSessionInfo(
            conversation_id=conversation_id,
            transport="websocket",
            ws_path=f"/ws/voice/{conversation_id}",
            audio_mime_type=self._tts.mime_type,
        )
