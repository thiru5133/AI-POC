"""Idempotent seed: one demo tenant with the Hotel domain profile."""

from app.core.config import get_settings
from app.database.session import get_session_factory
from app.domain.loader import load_profile_file, parse_profile
from app.auth.security import hash_password
from app.models import DomainProfileRow, Tenant, User
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
            )
        )


def seed(session_factory=None) -> None:
    settings = get_settings()
    session_factory = session_factory or get_session_factory()
    config = parse_profile(load_profile_file("hotel")).model_dump(by_alias=True)
    with session_factory() as session:
        if not session.get(Tenant, settings.default_tenant_id):
            session.add(Tenant(id=settings.default_tenant_id, name="Demo Tenant"))
            session.flush()
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
