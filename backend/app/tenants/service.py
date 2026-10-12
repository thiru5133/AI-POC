"""Businesses (tenants): provisioning by a superadmin, listing and enabling/disabling.

Every business partner belongs to exactly one domain (hotel, school, hospital, ...). The first partner of a domain
also creates that domain's *marketplace*: a shared assistant customers can use to compare all of its partners.
"""

import asyncio
from collections.abc import Callable

from sqlalchemy import false, func, select, true
from sqlalchemy.orm import Session

from app.auth import security
from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.domain import catalog
from app.models import Domain, DomainProfileRow, Tenant, User
from app.notifications.email import ConsoleEmailSender, EmailSender, credentials_email
from app.repositories.users import UserRepository

MARKETPLACE_MIN_PARTNERS = 2  # comparing needs at least two partners to be worth offering


class InvalidDomainError(AppError):
    status_code = 422
    code = "invalid_domain"


def create_organization(session: Session, name: str, domain: Domain, marketplace: bool = False) -> Tenant:
    """New tenant of `domain` with a starting profile built from the domain's master data."""
    definition = catalog.BY_KEY[domain.key]
    tenant = Tenant(name=name, domain_id=domain.id, is_marketplace=marketplace)
    session.add(tenant)
    session.flush()
    config = catalog.marketplace_profile_config(definition, name) if marketplace else catalog.profile_config(definition, name)
    from app.domain.loader import parse_profile

    session.add(
        DomainProfileRow(
            tenant_id=tenant.id,
            name=name,
            domain_type=domain.key,
            config=parse_profile(config).model_dump(by_alias=True),
        )
    )
    session.flush()
    return tenant


def ensure_marketplace(session: Session, domain: Domain) -> Tenant:
    existing = session.scalars(
        select(Tenant).where(Tenant.domain_id == domain.id, Tenant.is_marketplace == true())
    ).first()
    return existing or create_organization(session, f"All {domain.name} (compare)", domain, marketplace=True)


class BusinessService:
    """What the superadmin does with businesses. Sync DB work runs in a worker thread."""

    def __init__(
        self, session_factory: Callable[[], Session], settings: Settings, email: EmailSender | None = None
    ):
        self._sf = session_factory
        self._settings = settings
        self._email = email or ConsoleEmailSender()

    @staticmethod
    def _first_admins(session: Session, tenant_ids: list[str]) -> dict[str, User]:
        rows = session.scalars(
            select(User).where(User.role == "admin", User.tenant_id.in_(tenant_ids)).order_by(User.created_at)
        )
        admins: dict[str, User] = {}
        for user in rows:
            admins.setdefault(user.tenant_id, user)
        return admins

    @staticmethod
    def _view(tenant: Tenant, admin: User | None, domain: Domain | None) -> dict:
        return {
            "id": tenant.id,
            "name": tenant.name,
            "is_active": tenant.is_active,
            "created_at": tenant.created_at,
            "domain_id": tenant.domain_id,
            "domain_name": domain.name if domain else None,
            "admin_name": admin.name if admin else None,
            "admin_email": admin.email if admin else None,
        }

    def _create(self, name: str, admin_name: str, admin_email: str, domain_id: str) -> dict:
        admin_email = admin_email.strip().lower()
        with self._sf() as session:
            domain = session.get(Domain, domain_id)
            if domain is None or not domain.is_active:
                raise InvalidDomainError("Choose a domain for this business")
            users = UserRepository(session)
            if users.get_by_email(admin_email):
                raise ConflictError("An account with this email already exists")
            if session.scalar(select(Tenant.id).where(func.lower(Tenant.name) == name.lower())):
                raise ConflictError("A business with this name already exists")
            tenant = create_organization(session, name, domain)
            ensure_marketplace(session, domain)
            password = security.generate_password()
            admin = users.add(
                User(
                    email=admin_email,
                    name=admin_name,
                    password_hash=security.hash_password(password),
                    role="admin",
                    status="active",
                    tenant_id=tenant.id,
                )
            )
            # Sent before the commit: if delivery fails nothing is created and the superadmin can simply retry,
            # instead of leaving an admin whose password nobody received.
            subject, body = credentials_email(
                admin_name, name, admin_email, password, f"{self._settings.app_base_url.rstrip('/')}/login"
            )
            self._email.send(admin_email, subject, body)
            session.commit()
            return self._view(tenant, admin, domain)

    def _list(self, q: str | None) -> list[dict]:
        with self._sf() as session:
            stmt = select(Tenant).where(Tenant.is_marketplace == false()).order_by(Tenant.created_at.desc(), Tenant.id)
            if q and q.strip():
                stmt = stmt.where(func.lower(Tenant.name).like(f"%{q.strip().lower()}%"))
            tenants = list(session.scalars(stmt))
            admins = self._first_admins(session, [t.id for t in tenants])
            domains = {d.id: d for d in session.scalars(select(Domain))}
            return [self._view(t, admins.get(t.id), domains.get(t.domain_id)) for t in tenants]

    def _set_active(self, tenant_id: str, active: bool) -> dict:
        with self._sf() as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None or tenant.is_marketplace:
                raise NotFoundError("Business not found")
            tenant.is_active = active
            # A disabled business locks out its admins too; enabling it restores them.
            admins = list(
                session.scalars(
                    select(User).where(User.role == "admin", User.tenant_id == tenant_id).order_by(User.created_at)
                )
            )
            for admin in admins:
                admin.status = "active" if active else "disabled"
                if not active:
                    UserRepository(session).revoke_all_tokens(admin.id)
            session.commit()
            return self._view(tenant, admins[0] if admins else None, session.get(Domain, tenant.domain_id))

    def _list_domains(self) -> list[dict]:
        with self._sf() as session:
            rows = session.scalars(select(Domain).where(Domain.is_active == true()).order_by(Domain.name))
            return [{"id": d.id, "key": d.key, "name": d.name, "description": d.description} for d in rows]

    def _list_public(self) -> list[dict]:
        """Active partners, plus each domain's compare-all assistant once it has enough partners."""
        with self._sf() as session:
            domains = {d.id: d for d in session.scalars(select(Domain))}
            tenants = list(
                session.scalars(select(Tenant).where(Tenant.is_active == true()).order_by(Tenant.name))
            )
            partners_per_domain: dict[str, int] = {}
            for t in tenants:
                if not t.is_marketplace and t.domain_id:
                    partners_per_domain[t.domain_id] = partners_per_domain.get(t.domain_id, 0) + 1
            out = []
            for t in tenants:
                if t.is_marketplace and partners_per_domain.get(t.domain_id, 0) < MARKETPLACE_MIN_PARTNERS:
                    continue
                domain = domains.get(t.domain_id)
                out.append(
                    {
                        "id": t.id,
                        "name": t.name,
                        "domain_name": domain.name if domain else None,
                        "is_marketplace": t.is_marketplace,
                    }
                )
            return out

    async def create(self, name: str, admin_name: str, admin_email: str, domain_id: str) -> dict:
        return await asyncio.to_thread(self._create, name, admin_name, admin_email, domain_id)

    async def list_all(self, q: str | None = None) -> list[dict]:
        return await asyncio.to_thread(self._list, q)

    async def set_active(self, tenant_id: str, active: bool) -> dict:
        return await asyncio.to_thread(self._set_active, tenant_id, active)

    async def list_domains(self) -> list[dict]:
        return await asyncio.to_thread(self._list_domains)

    async def list_public(self) -> list[dict]:
        return await asyncio.to_thread(self._list_public)
