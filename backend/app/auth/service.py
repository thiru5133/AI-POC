import asyncio
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import security
from app.auth.ratelimit import LoginRateLimiter, login_limiter
from app.core.config import Settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.models import RefreshToken, Tenant, User
from app.repositories.users import UserRepository

_BLOCKED = {
    "pending": "Your account is awaiting superadmin approval.",
    "rejected": "Your onboarding request was rejected.",
    "disabled": "Your account has been disabled.",
}


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_name(name: str) -> str:
    return " ".join(name.split())  # trim and collapse inner whitespace


class AuthService:
    """Registration, login, token rotation and onboarding review. Sync DB work runs in a worker thread."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        settings: Settings,
        limiter: LoginRateLimiter = login_limiter,
    ):
        self._sf = session_factory
        self._settings = settings
        self._limiter = limiter

    # ---- sync implementations ----
    def _register(self, name: str, email: str, password: str) -> User:
        email = normalize_email(email)
        name = normalize_name(name)
        with self._sf() as session:
            repo = UserRepository(session)
            if repo.get_by_email(email):
                raise ConflictError("An account with this email already exists")
            if repo.get_by_name(name):
                raise ConflictError("That name is already taken")
            user = User(
                email=email,
                name=name,
                password_hash=security.hash_password(password),
                role="admin",
                status="pending",
            )
            try:
                repo.add(user)
                session.commit()
            except IntegrityError:
                session.rollback()
                raise ConflictError("An account with this email or name already exists") from None
            return user

    def _issue_tokens(self, repo: UserRepository, user: User) -> tuple[str, str]:
        access = security.create_access_token(self._settings, user.id, user.role, user.tenant_id)
        raw, token_hash = security.new_refresh_token()
        repo.add_refresh_token(
            RefreshToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=security.utcnow() + timedelta(days=self._settings.refresh_token_days),
            )
        )
        return access, raw

    def _login(self, identifier: str, password: str, client: str) -> tuple[User, str, str]:
        # Names cannot contain "@" (enforced at registration), so the form of the identifier is unambiguous.
        identifier = normalize_email(identifier) if "@" in identifier else normalize_name(identifier).lower()
        key = f"{identifier}|{client}"
        self._limiter.check(key)
        with self._sf() as session:
            repo = UserRepository(session)
            user = repo.get_by_email(identifier) if "@" in identifier else repo.get_by_name(identifier)
            ok = security.verify_password(user.password_hash if user else security.DUMMY_HASH, password)
            if user is None or not ok:
                self._limiter.record_failure(key)
                raise UnauthorizedError("Invalid email or password")
            if user.status != "active":
                raise ForbiddenError(_BLOCKED.get(user.status, "Account not active"), f"account_{user.status}")
            self._limiter.reset(key)
            access, raw = self._issue_tokens(repo, user)
            session.commit()
            return user, access, raw

    def _refresh(self, raw: str) -> tuple[User, str, str]:
        with self._sf() as session:
            repo = UserRepository(session)
            token = repo.get_refresh_token(security.hash_token(raw))
            if token is None:
                raise UnauthorizedError("Invalid session")
            if token.revoked_at is not None:
                # A rotated token being replayed means it was likely stolen: kill the whole family.
                repo.revoke_all_tokens(token.user_id)
                session.commit()
                raise UnauthorizedError("Invalid session")
            user = repo.get(token.user_id)
            if token.expires_at <= security.utcnow() or user is None or user.status != "active":
                raise UnauthorizedError("Session expired")
            token.revoked_at = security.utcnow()
            access, new_raw = self._issue_tokens(repo, user)
            session.commit()
            return user, access, new_raw

    def _logout(self, raw: str) -> None:
        with self._sf() as session:
            token = UserRepository(session).get_refresh_token(security.hash_token(raw))
            if token and token.revoked_at is None:
                token.revoked_at = security.utcnow()
                session.commit()

    def _get_user(self, user_id: str) -> User | None:
        with self._sf() as session:
            return UserRepository(session).get(user_id)

    def _list_requests(self, status: str | None) -> list[User]:
        with self._sf() as session:
            return UserRepository(session).list_admins(status)

    def _search_users(
        self, status: str | None, role: str | None, q: str | None, limit: int, offset: int
    ) -> tuple[list[User], int, dict[str, int]]:
        with self._sf() as session:
            repo = UserRepository(session)
            rows, total = repo.search(status, role, q, limit, offset)
            return rows, total, repo.status_counts(role, q)

    def _user_detail(self, user_id: str) -> tuple[User, str | None, str | None]:
        with self._sf() as session:
            repo = UserRepository(session)
            user = repo.get(user_id)
            if user is None:
                raise NotFoundError("User not found")
            reviewer = repo.get(user.reviewed_by) if user.reviewed_by else None
            tenant = session.get(Tenant, user.tenant_id) if user.tenant_id else None
            return user, (reviewer.name if reviewer else None), (tenant.name if tenant else None)

    def _review(self, request_id: str, reviewer_id: str, approve: bool, reason: str | None) -> User:
        with self._sf() as session:
            repo = UserRepository(session)
            user = repo.get(request_id)
            if user is None or user.role != "admin":
                raise NotFoundError("Onboarding request not found")
            if user.status != "pending":
                raise ConflictError(f"Request already {user.status}")
            user.status = "active" if approve else "rejected"
            user.tenant_id = self._settings.default_tenant_id if approve else None
            user.rejection_reason = None if approve else (reason or None)
            user.reviewed_by = reviewer_id
            user.reviewed_at = security.utcnow()
            session.commit()
            return user

    # ---- async API ----
    async def register(self, name: str, email: str, password: str) -> User:
        return await asyncio.to_thread(self._register, name, email, password)

    async def login(self, identifier: str, password: str, client: str) -> tuple[User, str, str]:
        return await asyncio.to_thread(self._login, identifier, password, client)

    async def refresh(self, raw: str) -> tuple[User, str, str]:
        return await asyncio.to_thread(self._refresh, raw)

    async def logout(self, raw: str) -> None:
        await asyncio.to_thread(self._logout, raw)

    async def get_user(self, user_id: str) -> User | None:
        return await asyncio.to_thread(self._get_user, user_id)

    async def list_requests(self, status: str | None) -> list[User]:
        return await asyncio.to_thread(self._list_requests, status)

    async def approve(self, request_id: str, reviewer_id: str) -> User:
        return await asyncio.to_thread(self._review, request_id, reviewer_id, True, None)

    async def reject(self, request_id: str, reviewer_id: str, reason: str | None) -> User:
        return await asyncio.to_thread(self._review, request_id, reviewer_id, False, reason)

    async def search_users(
        self, status: str | None, role: str | None, q: str | None, limit: int, offset: int
    ) -> tuple[list[User], int, dict[str, int]]:
        return await asyncio.to_thread(self._search_users, status, role, q, limit, offset)

    async def user_detail(self, user_id: str) -> tuple[User, str | None, str | None]:
        return await asyncio.to_thread(self._user_detail, user_id)
