import asyncio
import hmac
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import security
from app.auth.ratelimit import LoginRateLimiter, login_limiter
from app.core.config import Settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, RateLimitedError, UnauthorizedError
from app.models import EmailOtp, RefreshToken, Tenant, User
from app.notifications.email import ConsoleEmailSender, EmailSender, otp_email
from app.repositories.users import UserRepository

_BLOCKED = {
    "pending": "Your account is not active yet.",
    "rejected": "Your account is not active.",
    "disabled": "Your account has been disabled.",
}


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_name(name: str) -> str:
    return " ".join(name.split())  # trim and collapse inner whitespace


class AuthService:
    """Customer sign-up, login and token rotation. Sync DB work runs in a worker thread."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        settings: Settings,
        limiter: LoginRateLimiter = login_limiter,
        email: EmailSender | None = None,
    ):
        self._sf = session_factory
        self._settings = settings
        self._limiter = limiter
        self._email = email or ConsoleEmailSender()

    # ---- sync implementations ----
    def _register(self, name: str, email: str, password: str) -> User:
        """Customer sign-up: active immediately, no tenant (they choose a business to talk to later)."""
        email = normalize_email(email)
        name = normalize_name(name)
        with self._sf() as session:
            repo = UserRepository(session)
            if repo.get_by_email(email):
                raise ConflictError("An account with this email already exists")
            user = User(
                email=email, name=name, password_hash=security.hash_password(password), role="user", status="active"
            )
            try:
                repo.add(user)
                self._issue_otp(session, user)  # a failed email aborts the sign-up: nobody is left unable to verify
                session.commit()
            except IntegrityError:
                session.rollback()
                raise ConflictError("An account with this email already exists") from None
            return user

    # ---- one-time codes (first login) ----
    def _issue_otp(self, session: Session, user: User) -> None:
        """Replaces any open code with a fresh one and emails it. Raises if the email cannot be sent."""
        now = security.utcnow()
        for old in session.scalars(select(EmailOtp).where(EmailOtp.user_id == user.id, EmailOtp.consumed_at.is_(None))):
            old.consumed_at = now
        code = security.generate_otp()
        session.add(
            EmailOtp(
                user_id=user.id,
                code_hash=security.hash_otp(user.id, code),
                expires_at=now + timedelta(minutes=self._settings.otp_minutes),
            )
        )
        session.flush()
        subject, body = otp_email(user.name, code, self._settings.otp_minutes)
        self._email.send(user.email, subject, body)

    def _resend_otp(self, email: str) -> None:
        """Silent for unknown, verified or blocked accounts, so it cannot be used to probe which emails exist."""
        with self._sf() as session:
            user = UserRepository(session).get_by_email(normalize_email(email))
            if user is None or user.status != "active" or user.email_verified_at is not None:
                return
            latest = session.scalars(
                select(EmailOtp).where(EmailOtp.user_id == user.id).order_by(EmailOtp.created_at.desc())
            ).first()
            if latest and (security.utcnow() - latest.created_at).total_seconds() < self._settings.otp_resend_seconds:
                raise RateLimitedError("Please wait a moment before asking for another code")
            self._issue_otp(session, user)
            session.commit()

    def _verify_otp(self, email: str, code: str, client: str) -> tuple[User, str, str]:
        email = normalize_email(email)
        key = f"otp|{email}|{client}"
        self._limiter.check(key)
        invalid = UnauthorizedError("That code is not valid or has expired")
        with self._sf() as session:
            repo = UserRepository(session)
            user = repo.get_by_email(email)
            if user is None or user.status != "active":
                self._limiter.record_failure(key)
                raise invalid
            otp = session.scalars(
                select(EmailOtp)
                .where(EmailOtp.user_id == user.id, EmailOtp.consumed_at.is_(None))
                .order_by(EmailOtp.created_at.desc())
            ).first()
            now = security.utcnow()
            if otp is None or otp.expires_at <= now or otp.attempts >= self._settings.otp_max_attempts:
                self._limiter.record_failure(key)
                raise invalid
            if not hmac.compare_digest(otp.code_hash, security.hash_otp(user.id, code.strip())):
                otp.attempts += 1
                session.commit()
                self._limiter.record_failure(key)
                raise invalid
            otp.consumed_at = now
            user.email_verified_at = user.email_verified_at or now
            self._limiter.reset(key)
            access, raw = self._issue_tokens(repo, user)
            session.commit()
            return user, access, raw

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

    def _login(self, identifier: str, password: str, client: str) -> tuple[User, str | None, str | None]:
        """(user, access, refresh); access and refresh are None when the account must first confirm its email
        with the one-time code that was just sent."""
        identifier = normalize_email(identifier)
        key = f"{identifier}|{client}"
        self._limiter.check(key)
        with self._sf() as session:
            repo = UserRepository(session)
            user = repo.get_by_email(identifier)
            ok = security.verify_password(user.password_hash if user else security.DUMMY_HASH, password)
            if user is None or not ok:
                self._limiter.record_failure(key)
                raise UnauthorizedError("Invalid email or password")
            if user.status != "active":
                raise ForbiddenError(_BLOCKED.get(user.status, "Account not active"), f"account_{user.status}")
            self._limiter.reset(key)
            if user.email_verified_at is None:
                self._issue_otp(session, user)
                session.commit()
                return user, None, None
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
            if token.expires_at <= security.utcnow() or user is None or user.status != "active" or user.email_verified_at is None:
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

    def _is_active_business(self, tenant_id: str) -> bool:
        with self._sf() as session:
            tenant = session.get(Tenant, tenant_id)
            return bool(tenant and tenant.is_active)

    def _search_users(
        self, status: str | None, role: str | None, q: str | None, limit: int, offset: int
    ) -> tuple[list[User], int, dict[str, int]]:
        with self._sf() as session:
            repo = UserRepository(session)
            rows, total = repo.search(status, role, q, limit, offset)
            return rows, total, repo.status_counts(role, q)

    def _user_detail(self, user_id: str) -> tuple[User, str | None]:
        with self._sf() as session:
            user = UserRepository(session).get(user_id)
            if user is None:
                raise NotFoundError("User not found")
            tenant = session.get(Tenant, user.tenant_id) if user.tenant_id else None
            return user, (tenant.name if tenant else None)

    # ---- async API ----
    async def register(self, name: str, email: str, password: str) -> User:
        return await asyncio.to_thread(self._register, name, email, password)

    async def login(self, identifier: str, password: str, client: str) -> tuple[User, str | None, str | None]:
        return await asyncio.to_thread(self._login, identifier, password, client)

    async def verify_otp(self, email: str, code: str, client: str) -> tuple[User, str, str]:
        return await asyncio.to_thread(self._verify_otp, email, code, client)

    async def resend_otp(self, email: str) -> None:
        await asyncio.to_thread(self._resend_otp, email)

    async def refresh(self, raw: str) -> tuple[User, str, str]:
        return await asyncio.to_thread(self._refresh, raw)

    async def logout(self, raw: str) -> None:
        await asyncio.to_thread(self._logout, raw)

    async def get_user(self, user_id: str) -> User | None:
        return await asyncio.to_thread(self._get_user, user_id)

    async def is_active_business(self, tenant_id: str) -> bool:
        return await asyncio.to_thread(self._is_active_business, tenant_id)

    async def search_users(
        self, status: str | None, role: str | None, q: str | None, limit: int, offset: int
    ) -> tuple[list[User], int, dict[str, int]]:
        return await asyncio.to_thread(self._search_users, status, role, q, limit, offset)

    async def user_detail(self, user_id: str) -> tuple[User, str | None]:
        return await asyncio.to_thread(self._user_detail, user_id)
