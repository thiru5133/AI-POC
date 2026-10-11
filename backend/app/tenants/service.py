"""Organizations (tenants): provisioning on approval."""

from sqlalchemy.orm import Session

from app.domain.loader import generic_profile_config
from app.models import DomainProfileRow, Tenant


def create_organization(session: Session, name: str) -> Tenant:
    """New tenant with a minimal profile (knowledge comes from uploaded documents)."""
    tenant = Tenant(name=name)
    session.add(tenant)
    session.flush()
    session.add(
        DomainProfileRow(
            tenant_id=tenant.id,
            name=name,
            domain_type="generic",
            config=generic_profile_config(name),
        )
    )
    session.flush()
    return tenant
