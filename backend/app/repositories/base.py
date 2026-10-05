from typing import Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class TenantScopedRepository(Generic[T]):
    """Every query goes through `_select()`, which always filters on tenant_id.

    Repositories cannot be constructed without a tenant, so cross-tenant reads are structurally impossible.
    """

    model: type[T]

    def __init__(self, session: Session, tenant_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.session = session
        self.tenant_id = tenant_id

    def _select(self) -> Select:
        return select(self.model).where(self.model.tenant_id == self.tenant_id)  # type: ignore[attr-defined]

    def get(self, entity_id: str) -> T | None:
        return self.session.scalars(self._select().where(self.model.id == entity_id)).first()  # type: ignore[attr-defined]

    def add(self, entity: T) -> T:
        entity.tenant_id = self.tenant_id  # type: ignore[attr-defined]  # never trust caller-supplied tenant
        self.session.add(entity)
        self.session.flush()
        return entity
