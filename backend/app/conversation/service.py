import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.conversation.context import ConversationContext
from app.conversation.engine import ConversationEngine
from app.core.errors import NotFoundError
from app.domain.loader import parse_profile
from app.domain.profile import DomainProfile
from app.models import Conversation
from app.repositories.conversations import ConversationRepository, DomainProfileRepository

log = logging.getLogger(__name__)

HISTORY_LIMIT = 40


@dataclass
class TurnState:
    profile: DomainProfile
    ctx: ConversationContext
    history: list[dict[str, Any]]


class ConversationService:
    """Orchestrates persistence (tenant-scoped repositories) around the pure ConversationEngine."""

    def __init__(self, session_factory: Callable[[], Session], engine: ConversationEngine):
        self._sf = session_factory
        self.engine = engine

    # ---- sync DB helpers (run in a worker thread from async callers) ----
    def _start(self, tenant_id: str, user_id: str | None) -> tuple[str, str]:
        with self._sf() as session:
            profile_row = DomainProfileRepository(session, tenant_id).get_active()
            if profile_row is None:
                raise NotFoundError("Domain profile not found")
            profile = parse_profile(profile_row.config)
            repo = ConversationRepository(session, tenant_id, user_id)
            conv = repo.add(Conversation(domain_profile_id=profile_row.id, context={}))
            greeting = profile.identity.greeting
            repo.add_message(conv.id, "assistant", greeting)
            session.commit()
            return conv.id, greeting

    def _load(self, tenant_id: str, conversation_id: str, user_id: str | None = None) -> TurnState:
        with self._sf() as session:
            repo = ConversationRepository(session, tenant_id, user_id)
            conv = repo.get(conversation_id)
            if conv is None:
                raise NotFoundError("Conversation not found")
            profile_row = DomainProfileRepository(session, tenant_id).get(conv.domain_profile_id)
            profile = parse_profile(profile_row.config)
            ctx = ConversationContext(
                **{**(conv.context or {}), "session_id": conv.id, "tenant_id": tenant_id,
                   "domain_profile_id": conv.domain_profile_id}
            )
            history = [
                {"role": m.role, "content": m.content} for m in repo.messages(conv.id, HISTORY_LIMIT)
            ]
            return TurnState(profile, ctx, _normalize_history(history))

    def _save_turn(self, tenant_id: str, user_id: str | None, ctx: ConversationContext, user_text: str, reply: str) -> None:
        with self._sf() as session:
            repo = ConversationRepository(session, tenant_id, user_id)
            conv = repo.get(ctx.session_id)
            repo.add_message(ctx.session_id, "user", user_text, intent=ctx.intent)
            if reply.strip():
                repo.add_message(ctx.session_id, "assistant", reply.strip())
            conv.context = ctx.model_dump(exclude={"session_id", "tenant_id", "domain_profile_id"})
            session.commit()

    def _list(self, tenant_id: str, user_id: str | None, limit: int, offset: int, include_empty: bool) -> dict[str, Any]:
        with self._sf() as session:
            items, total = ConversationRepository(session, tenant_id, user_id).list_summaries(limit, offset, include_empty)
            return {"items": items, "total": total, "limit": limit, "offset": offset}

    def _get(self, tenant_id: str, conversation_id: str, user_id: str | None) -> dict[str, Any]:
        with self._sf() as session:
            repo = ConversationRepository(session, tenant_id, user_id)
            conv = repo.get(conversation_id)
            if conv is None:
                raise NotFoundError("Conversation not found")
            return {
                "id": conv.id,
                "domain_profile_id": conv.domain_profile_id,
                "status": conv.status,
                "started_at": conv.started_at,
                "context": conv.context or {},
                "messages": [
                    {"role": m.role, "text": m.content, "intent": m.intent, "created_at": m.created_at}
                    for m in repo.messages(conv.id)
                ],
            }

    # ---- async API ----
    # `user_id` is set when the caller is a customer: they only see conversations they started themselves.
    async def start(self, tenant_id: str, user_id: str | None = None) -> tuple[str, str]:
        return await asyncio.to_thread(self._start, tenant_id, user_id)

    async def list(
        self, tenant_id: str, limit: int = 30, offset: int = 0, include_empty: bool = False, user_id: str | None = None
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self._list, tenant_id, user_id, limit, offset, include_empty)

    async def get(self, tenant_id: str, conversation_id: str, user_id: str | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._get, tenant_id, conversation_id, user_id)

    async def get_profile(self, tenant_id: str, conversation_id: str, user_id: str | None = None) -> DomainProfile:
        return (await asyncio.to_thread(self._load, tenant_id, conversation_id, user_id)).profile

    async def reply_stream(
        self, tenant_id: str, conversation_id: str, user_text: str, user_id: str | None = None
    ) -> AsyncIterator[str]:
        """Streams the assistant reply; persists the turn (also when cancelled mid-reply, e.g. barge-in)."""
        state = await asyncio.to_thread(self._load, tenant_id, conversation_id, user_id)
        collected: list[str] = []
        try:
            async for delta in self.engine.run_turn(state.profile, state.ctx, state.history, user_text):
                collected.append(delta)
                yield delta
        finally:
            await asyncio.shield(
                asyncio.to_thread(self._save_turn, tenant_id, user_id, state.ctx, user_text, "".join(collected))
            )

    async def reply(self, tenant_id: str, conversation_id: str, user_text: str, user_id: str | None = None) -> str:
        return "".join(
            [d async for d in self.reply_stream(tenant_id, conversation_id, user_text, user_id)]
        ).strip()


def _normalize_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic requires the first message to be 'user' and roles to alternate: merge/drop accordingly."""
    out: list[dict[str, Any]] = []
    for msg in history:
        if not out and msg["role"] != "user":
            continue  # drop the leading assistant greeting from the LLM transcript
        if out and out[-1]["role"] == msg["role"]:
            out[-1] = {"role": msg["role"], "content": f'{out[-1]["content"]}\n{msg["content"]}'}
        else:
            out.append(dict(msg))
    return out
