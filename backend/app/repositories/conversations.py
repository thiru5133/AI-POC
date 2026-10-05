from sqlalchemy import select

from app.models import Conversation, DomainProfileRow, Message
from app.repositories.base import TenantScopedRepository


class DomainProfileRepository(TenantScopedRepository[DomainProfileRow]):
    model = DomainProfileRow

    def list(self) -> list[DomainProfileRow]:
        return list(self.session.scalars(self._select().order_by(DomainProfileRow.created_at)))


class ConversationRepository(TenantScopedRepository[Conversation]):
    model = Conversation

    def add_message(self, conversation_id: str, role: str, content: str, intent: str | None = None) -> Message:
        msg = Message(conversation_id=conversation_id, role=role, content=content, intent=intent)
        msg.tenant_id = self.tenant_id
        self.session.add(msg)
        self.session.flush()
        return msg

    def messages(self, conversation_id: str, limit: int | None = None) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.tenant_id == self.tenant_id, Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        rows = list(self.session.scalars(stmt))
        return rows[-limit:] if limit else rows
