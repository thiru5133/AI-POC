"""Drives one browser voice call over a WebSocket.

client -> server: binary mic audio; JSON {"type": "interrupt"}
server -> client: JSON events (transcript.partial/final, assistant.text, assistant.audio_start/end,
                  assistant.interrupt, error) and binary TTS audio frames (one per sentence).
"""

import asyncio
import contextlib
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect

from app import usage
from app.conversation.chunker import sentences
from app.conversation.service import ConversationService
from app.core.errors import AppError
from app.voice.base import STTProvider, TTSProvider

log = logging.getLogger(__name__)


class VoiceSession:
    def __init__(
        self,
        ws: WebSocket,
        service: ConversationService,
        stt: STTProvider,
        tts: TTSProvider,
        tenant_id: str,
        conversation_id: str,
        user_id: str | None = None,
    ):
        self.ws = ws
        self.service = service
        self.stt = stt
        self.tts = tts
        self.tenant_id = tenant_id
        self.conversation_id = conversation_id
        self.user_id = user_id
        self._turn: asyncio.Task | None = None
        self._speaking = False
        self._log_extra = {"tenant_id": tenant_id, "session_id": conversation_id}

    async def run(self) -> None:
        await self.ws.accept()
        started = time.monotonic()
        try:
            profile = await self.service.get_profile(self.tenant_id, self.conversation_id, self.user_id)
            stt = await self.stt.open(profile.identity.language)
        except AppError as exc:
            await self._send_error(exc.code, exc.message)
            await self.ws.close()
            return

        tasks: list[asyncio.Task] = []
        try:
            await self._speak(profile.identity.greeting)
            await self._send({"type": "assistant.audio_end"})
            tasks = [asyncio.create_task(self._receive(stt)), asyncio.create_task(self._transcripts(stt))]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("voice session failed", extra=self._log_extra)
            with contextlib.suppress(Exception):
                await self._send_error("voice_error", "Voice session failed")
        finally:
            for task in tasks:
                task.cancel()
            with contextlib.suppress(Exception):
                await self._cancel_turn()
            await stt.close()
            with contextlib.suppress(Exception):
                await self.service.record_usage(
                    self.tenant_id, self.conversation_id, usage.VOICE_SECONDS, round(time.monotonic() - started)
                )
            with contextlib.suppress(Exception):
                await self.ws.close()

    async def _receive(self, stt) -> None:
        while True:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes"):
                await stt.send_audio(msg["bytes"])
            elif msg.get("text") and '"interrupt"' in msg["text"]:
                await self._cancel_turn()

    async def _transcripts(self, stt) -> None:
        async for event in stt.events():
            if not event.is_final:
                await self._send({"type": "transcript.partial", "text": event.text})
                if self._speaking:  # barge-in: caller started talking over the assistant
                    await self._cancel_turn()
                continue
            await self._send({"type": "transcript.final", "text": event.text})
            await self._cancel_turn()
            self._turn = asyncio.create_task(self._answer(event.text))

    async def _answer(self, user_text: str) -> None:
        try:
            replies = self.service.reply_stream(self.tenant_id, self.conversation_id, user_text, self.user_id)
            async with contextlib.aclosing(replies), contextlib.aclosing(sentences(replies)) as chunks:
                async for sentence in chunks:
                    await self._speak(sentence)
            await self._send({"type": "assistant.audio_end"})
        except asyncio.CancelledError:
            raise
        except AppError as exc:
            await self._send_error(exc.code, exc.message)
        except Exception:
            log.exception("turn failed", extra=self._log_extra)
            await self._send_error("turn_failed", "Something went wrong answering that.")
        finally:
            self._speaking = False

    async def _speak(self, text: str) -> None:
        await self._send({"type": "assistant.text", "text": text})
        self._speaking = True
        audio = await self.tts.synthesize(text)
        await self.ws.send_bytes(audio)

    async def _cancel_turn(self) -> None:
        task, self._turn = self._turn, None
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            await self._send({"type": "assistant.interrupt"})
        self._speaking = False

    async def _send(self, payload: dict) -> None:
        await self.ws.send_json(payload)

    async def _send_error(self, code: str, message: str) -> None:
        await self._send({"type": "error", "code": code, "message": message})
