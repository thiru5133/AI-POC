from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app.models import Domain, PhoneNumber, Tenant
from app.repositories.base import TenantScopedRepository


class PhoneRepository(TenantScopedRepository[PhoneNumber]):
    model = PhoneNumber

    def get_for_tenant(self) -> PhoneNumber | None:
        return self.session.scalars(self._select()).first()

    def number_taken(self, number: str) -> bool:
        """Whether another business already uses `number` (numbers are unique across businesses)."""
        row = self.session.scalars(select(PhoneNumber).where(PhoneNumber.number == number)).first()
        return row is not None and row.tenant_id != self.tenant_id

    def save(self, number: str, transfer_number: str | None) -> PhoneNumber:
        row = self.get_for_tenant()
        if row is None:
            return self.add(PhoneNumber(number=number, transfer_number=transfer_number))
        row.number, row.transfer_number = number, transfer_number
        self.session.flush()
        return row

    def clear(self) -> None:
        row = self.get_for_tenant()
        if row is not None:
            self.session.delete(row)
            self.session.flush()


def business_for_number(session: Session, number: str) -> tuple[Tenant, PhoneNumber] | None:
    """The active business that answers calls on `number`. Deliberately not tenant-scoped: at this point the caller's
    business is exactly what is being looked up, from the number the carrier says was dialled."""
    row = session.execute(
        select(Tenant, PhoneNumber).join(PhoneNumber, PhoneNumber.tenant_id == Tenant.id).where(PhoneNumber.number == number)
    ).first()
    if row is None or not row[0].is_active:
        return None
    return row[0], row[1]


def domain_line_for(session: Session, tenant_id: str) -> tuple[str, str | None] | None:
    """(domain name, number of its shared compare-all line or None) for the domain a business belongs to."""
    tenant = session.get(Tenant, tenant_id)
    domain = session.get(Domain, tenant.domain_id) if tenant and tenant.domain_id else None
    if domain is None:
        return None
    market = session.scalars(select(Tenant).where(Tenant.domain_id == domain.id, Tenant.is_marketplace == true())).first()
    row = PhoneRepository(session, market.id).get_for_tenant() if market else None
    return domain.name, row.number if row else None
