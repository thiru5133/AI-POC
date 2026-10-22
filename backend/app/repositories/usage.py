from datetime import datetime

from sqlalchemy import func, select

from app.models import UsageEvent
from app.repositories.base import TenantScopedRepository
from app.usage import KINDS


class UsageRepository(TenantScopedRepository[UsageEvent]):
    model = UsageEvent

    def record(self, kind: str, quantity: int = 1, conversation_id: str | None = None) -> UsageEvent:
        if kind not in KINDS:
            raise ValueError(f"unknown usage kind {kind!r}")
        return self.add(UsageEvent(kind=kind, quantity=quantity, conversation_id=conversation_id))

    def totals(self, since: datetime) -> dict[str, int]:
        """Summed quantity per kind since `since`; every kind is present, 0 when unused."""
        rows = self.session.execute(
            select(UsageEvent.kind, func.sum(UsageEvent.quantity))
            .where(UsageEvent.tenant_id == self.tenant_id, UsageEvent.created_at >= since)
            .group_by(UsageEvent.kind)
        )
        out = {kind: 0 for kind in KINDS}
        out.update({kind: int(total or 0) for kind, total in rows})
        return out
