import asyncio
import logging
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.ai.base import LLMBusyError
from app.conversation.context import ConversationContext
from app.conversation.engine import ConversationEngine
from app.core.errors import NotFoundError
from app.domain.loader import parse_profile
from app.domain.profile import DomainProfile
from app.models import Conversation
from app.notifications.staff import StaffAlerts
from app import usage
from app.repositories.phone import PhoneRepository
from app.repositories.conversations import ConversationRepository, DomainProfileRepository
from app.repositories.usage import UsageRepository

log = logging.getLogger(__name__)

HISTORY_LIMIT = 40

BUSY_REPLY = "Sorry, we're very busy right now. Could you please say that again in a moment?"
OFFER_TRANSFER = (
    "I'm sorry, I'm having trouble with our system right now. Would you like me to connect you with someone from the team?"
)
OFFER_CALLBACK = (
    "I'm sorry, I'm having trouble with our system right now. Would you like me to ask someone from the team to contact you?"
)
ACCEPTED_TRANSFER = "Okay, I'm connecting you to the team now. Please hold."
ACCEPTED_CALLBACK = "Okay, I've let the team know, and someone will contact you as soon as possible."

_YES = {"yes", "yeah", "yep", "yup", "sure", "please", "okay", "ok", "fine", "definitely"}
_NO = {"no", "nope", "nah", "not", "never", "dont", "don't"}


def accepts_offer(text: str) -> bool:
    """Whether the caller said yes to an offer of a person (English; anything unclear counts as no)."""
    words = set(re.findall(r"[a-z']+", text.lower()))
    return bool(words & _YES) and not words & _NO


@dataclass
class TurnState:
    profile: DomainProfile
    ctx: ConversationContext
    history: list[dict[str, Any]]


class ConversationService:
    """Orchestrates persistence (tenant-scoped repositories) around the pure ConversationEngine."""

    def __init__(
        self, session_factory: Callable[[], Session], engine: ConversationEngine, alerts: StaffAlerts | None = None
    ):
        self._sf = session_factory
        self.engine = engine
        self._alerts = alerts
        self._tasks: set[asyncio.Task] = set()

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
            UsageRepository(session, tenant_id).record(usage.CONVERSATION, 1, conv.id)
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
            phone = PhoneRepository(session, tenant_id).get_for_tenant()
            ctx = ConversationContext(
                **{**(conv.context or {}), "session_id": conv.id, "tenant_id": tenant_id,
                   "domain_profile_id": conv.domain_profile_id, "business_phone": phone.number if phone else None}
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
            conv.context = ctx.model_dump(exclude={"session_id", "tenant_id", "domain_profile_id", "business_phone"})
            meter = UsageRepository(session, tenant_id)
            meter.record(usage.MESSAGE, 1, ctx.session_id)
            for kind, quantity in ctx.usage_log:
                meter.record(kind, quantity, ctx.session_id)
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
            async for delta in self._turn(state, user_text):
                collected.append(delta)
                yield delta
        finally:
            ping = self._needs_ping(state)
            await asyncio.shield(
                asyncio.to_thread(self._save_turn, tenant_id, user_id, state.ctx, user_text, "".join(collected))
            )
            if ping:
                self._ping_staff(tenant_id, state)

    async def _turn(self, state: TurnState, user_text: str) -> AsyncIterator[str]:
        """One turn. When the assistant itself breaks, the caller is told so and offered a person; their answer to that
        offer is handled here too, because the assistant may still be broken."""
        ctx = state.ctx
        if ctx.pending_offer:
            issue, ctx.pending_offer = ctx.pending_offer, None
            if accepts_offer(user_text):
                ctx.handoff_requested = True
                ctx.handoff_reason = f"The caller accepted a person after a system problem ({issue})."[:200]
                yield ACCEPTED_TRANSFER if ctx.transfer_available else ACCEPTED_CALLBACK
                return
        try:
            async for delta in self.engine.run_turn(state.profile, ctx, state.history, user_text):
                yield delta
        except LLMBusyError:
            log.warning("the model provider is rate limiting us", extra={"tenant_id": ctx.tenant_id, "session_id": ctx.session_id})
            yield BUSY_REPLY  # a passing limit: ask them to repeat, do not offer a person
        except Exception:
            log.exception("turn failed", extra={"tenant_id": ctx.tenant_id, "session_id": ctx.session_id})
            ctx.pending_offer = "the assistant could not answer"
            yield OFFER_TRANSFER if ctx.transfer_available else OFFER_CALLBACK

    def _needs_ping(self, state: TurnState) -> bool:
        """Whether this turn is the first to need a person: the business's people are pinged once per conversation."""
        ctx = state.ctx
        if self._alerts is None or not (ctx.handoff_requested or ctx.alert_reason):
            return False
        if ctx.staff_alerted:
            # An earlier, milder alert must not swallow an emergency: that one is sent again, once.
            if ctx.urgency != "emergency" or ctx.emergency_alerted:
                return False
            ctx.emergency_alerted = True
            return True
        ctx.staff_alerted = True
        ctx.emergency_alerted = ctx.urgency == "emergency"
        return True

    def _ping_staff(self, tenant_id: str, state: TurnState) -> None:
        ctx = state.ctx
        reason = ctx.handoff_reason or ctx.alert_reason or "They asked for a person."
        if ctx.urgency != "normal":
            reason += f" Caller state: {ctx.urgency}."
        task = asyncio.create_task(
            asyncio.to_thread(
                self._alerts.send,
                tenant_id,
                state.profile.identity.organization_name,
                reason,
                ctx.caller.phone,
                ctx.session_id,
                None if ctx.handoff_requested else f"System problem on a call at {state.profile.identity.organization_name}",
            )
        )
        self._tasks.add(task)  # keep a reference until it finishes
        task.add_done_callback(self._tasks.discard)

    def _claim_call_alert(self, tenant_id: str, call_id: str | None) -> tuple[bool, str | None, str]:
        """(should alert, conversation id, business name) for a call that ended badly. A call already alerted about
        during the conversation is not alerted again; the conversation is marked so a repeated report is ignored too."""
        with self._sf() as session:
            repo = ConversationRepository(session, tenant_id)
            recent = session.scalars(repo._select().order_by(Conversation.started_at.desc()).limit(20))
            conv = next((c for c in recent if call_id and (c.context or {}).get("call_id") == call_id), None)
            profile_row = DomainProfileRepository(session, tenant_id).get_active()
            org = parse_profile(profile_row.config).identity.organization_name if profile_row else "your business"
            if conv is None:
                return True, None, org
            if (conv.context or {}).get("staff_alerted"):
                return False, conv.id, org
            conv.context = {**(conv.context or {}), "staff_alerted": True}
            session.commit()
            return True, conv.id, org

    async def alert_call_ended(self, tenant_id: str, call_id: str | None, caller_phone: str | None, how: str) -> None:
        """A phone call ended because of an error or a dropped line: tell the business so it can call the person back."""
        if self._alerts is None:
            return
        should, conversation_id, org = await asyncio.to_thread(self._claim_call_alert, tenant_id, call_id)
        if not should:
            return
        await asyncio.to_thread(
            self._alerts.send,
            tenant_id,
            org,
            f"The call ended unexpectedly ({how}).",
            caller_phone,
            conversation_id,
            f"A call at {org} dropped",
        )

    async def update_context(self, tenant_id: str, conversation_id: str, fields: dict[str, Any]) -> None:
        """Merges `fields` into a conversation's saved context (how a call's channel and caller are recorded)."""

        def write() -> None:
            with self._sf() as session:
                conv = ConversationRepository(session, tenant_id).get(conversation_id)
                if conv is None:
                    raise NotFoundError("Conversation not found")
                conv.context = {**(conv.context or {}), **fields}
                session.commit()

        await asyncio.to_thread(write)

    async def record_usage(self, tenant_id: str, conversation_id: str, kind: str, quantity: int) -> None:
        def write() -> None:
            with self._sf() as session:
                UsageRepository(session, tenant_id).record(kind, quantity, conversation_id)
                session.commit()

        await asyncio.to_thread(write)

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
