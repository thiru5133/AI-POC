"""Idempotent seed: one demo tenant with the Hotel domain profile."""

from app.core.config import get_settings
from app.database.session import get_session_factory
from app.domain.loader import load_profile_file, parse_profile
from app.auth.security import hash_password
from app.domain.catalog import DOMAINS
from app.models import Domain, DomainProfileRow, Tenant, User
from app.auth.security import utcnow
from sqlalchemy import select
from app.repositories.users import UserRepository


def _seed_superadmin(session, settings) -> None:
    if not (settings.superadmin_email and settings.superadmin_password):
        return
    email = settings.superadmin_email.strip().lower()
    if UserRepository(session).get_by_email(email) is None:
        session.add(
            User(
                email=email,
                name="Super Admin",
                password_hash=hash_password(settings.superadmin_password),
                role="superadmin",
                status="active",
                email_verified_at=utcnow(),
            )
        )


def seed_domains(session) -> dict[str, Domain]:
    """Upserts the domain master data by key; returns key -> Domain."""
    existing = {d.key: d for d in session.scalars(select(Domain))}
    for d in DOMAINS:
        row = existing.get(d.key)
        if row is None:
            row = existing[d.key] = Domain(key=d.key, name=d.name, description=d.description)
            session.add(row)
    session.flush()
    return existing


def seed(session_factory=None) -> None:
    settings = get_settings()
    session_factory = session_factory or get_session_factory()
    config = parse_profile(load_profile_file("hotel")).model_dump(by_alias=True)
    with session_factory() as session:
        domains = seed_domains(session)
        demo = session.get(Tenant, settings.default_tenant_id)
        if demo is None:
            session.add(Tenant(id=settings.default_tenant_id, name="Demo Tenant", domain_id=domains["hotel"].id))
            session.flush()
        elif demo.domain_id is None:
            demo.domain_id = domains["hotel"].id
        row = session.get(DomainProfileRow, settings.default_domain_profile_id)
        if row is None:
            session.add(
                DomainProfileRow(
                    id=settings.default_domain_profile_id,
                    tenant_id=settings.default_tenant_id,
                    name="Demo Hotel",
                    domain_type="hotel",
                    config=config,
                )
            )
        else:
            row.config = config  # keep the seeded profile in sync with hotel.json
        _seed_superadmin(session, settings)
        session.commit()
    print("seed complete")


if __name__ == "__main__":
    seed()
