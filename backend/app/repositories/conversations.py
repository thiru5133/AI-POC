from sqlalchemy import exists, func, select, true

from app.models import Conversation, DomainProfileRow, Message
from app.repositories.base import TenantScopedRepository


class DomainProfileRepository(TenantScopedRepository[DomainProfileRow]):
    model = DomainProfileRow

    def get_active(self) -> DomainProfileRow | None:
        """The organization's live profile (oldest active one)."""
        stmt = self._select().where(DomainProfileRow.is_active == true()).order_by(DomainProfileRow.created_at)
        return self.session.scalars(stmt).first()

    def list(self) -> list[DomainProfileRow]:
        return list(self.session.scalars(self._select().order_by(DomainProfileRow.created_at)))


class ConversationRepository(TenantScopedRepository[Conversation]):
    model = Conversation

    def __init__(self, session, tenant_id: str, user_id: str | None = None):
        super().__init__(session, tenant_id)
        self.user_id = user_id  # set for a customer: they only ever see their own conversations

    def _select(self):
        stmt = super()._select()
        return stmt.where(Conversation.user_id == self.user_id) if self.user_id else stmt

    def add(self, entity):
        if self.user_id:
            entity.user_id = self.user_id
        return super().add(entity)

    def add_message(self, conversation_id: str, role: str, content: str, intent: str | None = None) -> Message:
        msg = Message(conversation_id=conversation_id, role=role, content=content, intent=intent)
        msg.tenant_id = self.tenant_id
        self.session.add(msg)
        self.session.flush()
        return msg

    def list_summaries(self, limit: int, offset: int, include_empty: bool = False) -> tuple[list[dict], int]:
        """This organization's conversations, newest first. Conversations where the caller never said anything
        (just the greeting) are left out unless `include_empty`."""
        base = self._select()
        if not include_empty:
            said_something = exists().where(
                Message.tenant_id == self.tenant_id, Message.conversation_id == Conversation.id, Message.role == "user"
            )
            base = base.where(said_something)
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        page = list(
            self.session.scalars(base.order_by(Conversation.started_at.desc(), Conversation.id).limit(limit).offset(offset))
        )
        ids = [c.id for c in page]
        counts: dict[str, tuple[int, object]] = {}
        previews: dict[str, str] = {}
        if ids:
            rows = self.session.execute(
                select(Message.conversation_id, func.count(), func.max(Message.created_at))
                .where(Message.tenant_id == self.tenant_id, Message.conversation_id.in_(ids))
                .group_by(Message.conversation_id)
            )
            counts = {cid: (n, last) for cid, n, last in rows}
            first_user = self.session.execute(
                select(Message.conversation_id, Message.content)
                .where(Message.tenant_id == self.tenant_id, Message.conversation_id.in_(ids), Message.role == "user")
                .order_by(Message.created_at, Message.id)
            )
            for cid, content in first_user:
                previews.setdefault(cid, content)
        return (
            [
                {
                    "id": c.id,
                    "started_at": c.started_at,
                    "status": c.status,
                    "message_count": counts.get(c.id, (0, None))[0],
                    "last_message_at": counts.get(c.id, (0, None))[1],
                    "preview": previews.get(c.id, "")[:160],
                }
                for c in page
            ],
            total,
        )

    def messages(self, conversation_id: str, limit: int | None = None) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.tenant_id == self.tenant_id, Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        rows = list(self.session.scalars(stmt))
        return rows[-limit:] if limit else rows
