"""Staff accounts: login sessions and user management."""

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, true, update
from sqlalchemy.engine import Connection

from app.db import sessions, users
from app.passwords import DUMMY_HASH, MAX_LENGTH, MIN_LENGTH, hash_password, verify_password
from app.service import DomainError

SESSION_HOURS = 8
ROLES = ("superadmin", "admin")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _public(row) -> dict:
    """A user without the password hash."""
    data = dict(row._mapping)
    data.pop("password_hash", None)
    return data


class LoginLimiter:
    """Failed logins per email+client (in memory: per process only)."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 900):
        self._max = max_failures
        self._window = window_seconds
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - self._window
        self._failures[key] = [t for t in self._failures.get(key, []) if t > cutoff]
        return self._failures[key]

    def check(self, key: str) -> None:
        if len(self._recent(key)) >= self._max:
            raise DomainError(429, "too_many_attempts", "Too many failed logins. Try again in a few minutes.")

    def record_failure(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._failures.clear()
        else:
            self._failures.pop(key, None)


login_limiter = LoginLimiter()


def check_password_policy(password: str) -> None:
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise DomainError(422, "weak_password", f"The password must be {MIN_LENGTH}-{MAX_LENGTH} characters")


# ---------- sessions ----------
def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def login(conn: Connection, email: str, password: str, client: str) -> tuple[dict, str]:
    """Returns (user, session token) or raises 401 (identical message for unknown email and wrong password)."""
    email = email.strip().lower()
    key = f"{email}|{client}"
    login_limiter.check(key)
    row = conn.execute(select(users).where(users.c.email == email)).first()
    ok = verify_password(row.password_hash if row else DUMMY_HASH, password)
    if row is None or not ok or not row.active:
        login_limiter.record_failure(key)
        raise DomainError(401, "invalid_credentials", "Invalid email or password")
    login_limiter.reset(key)
    raw = secrets.token_urlsafe(32)
    now = _now()
    conn.execute(delete(sessions).where(sessions.c.expires_at < now))  # housekeeping
    conn.execute(sessions.insert().values(token_hash=_token_hash(raw), user_id=row.id, created_at=now, expires_at=now + timedelta(hours=SESSION_HOURS)))
    conn.execute(update(users).where(users.c.id == row.id).values(last_login_at=now))
    conn.commit()
    return _public(row), raw


def user_for_token(conn: Connection, raw: str | None) -> dict | None:
    if not raw:
        return None
    row = conn.execute(
        select(users)
        .select_from(sessions.join(users, users.c.id == sessions.c.user_id))
        .where(sessions.c.token_hash == _token_hash(raw), sessions.c.expires_at > _now(), users.c.active == true())
    ).first()
    return _public(row) if row else None


def logout(conn: Connection, raw: str | None) -> None:
    if raw:
        conn.execute(delete(sessions).where(sessions.c.token_hash == _token_hash(raw)))
        conn.commit()


def _revoke_all(conn: Connection, user_id: int) -> None:
    conn.execute(delete(sessions).where(sessions.c.user_id == user_id))


# ---------- user management ----------
def list_users(conn: Connection) -> list[dict]:
    return [_public(r) for r in conn.execute(select(users).order_by(users.c.id))]


def get_user(conn: Connection, user_id: int) -> dict:
    row = conn.execute(select(users).where(users.c.id == user_id)).first()
    if row is None:
        raise DomainError(404, "user_not_found", "User not found")
    return _public(row)


def _active_superadmins(conn: Connection) -> int:
    return conn.execute(
        select(func.count()).select_from(users).where(users.c.role == "superadmin", users.c.active == true())
    ).scalar() or 0


def create_user(conn: Connection, email: str, name: str, password: str, role: str) -> dict:
    email = email.strip().lower()
    if role not in ROLES:
        raise DomainError(422, "invalid_role", f"Role must be one of: {', '.join(ROLES)}")
    check_password_policy(password)
    if conn.execute(select(users.c.id).where(users.c.email == email)).first():
        raise DomainError(409, "email_taken", "A user with that email already exists")
    conn.execute(
        users.insert().values(
            email=email, name=" ".join(name.split()), password_hash=hash_password(password), role=role, active=True, created_at=_now()
        )
    )
    conn.commit()
    return _public(conn.execute(select(users).where(users.c.email == email)).first())


def update_user(
    conn: Connection, user_id: int, acting_user_id: int, name: str | None, role: str | None, active: bool | None
) -> dict:
    target = get_user(conn, user_id)
    values: dict = {}
    if name is not None:
        values["name"] = " ".join(name.split())
    if role is not None:
        if role not in ROLES:
            raise DomainError(422, "invalid_role", f"Role must be one of: {', '.join(ROLES)}")
        values["role"] = role
    if active is not None:
        values["active"] = active
    losing_superadmin = target["role"] == "superadmin" and target["active"] and (
        values.get("role", target["role"]) != "superadmin" or values.get("active", True) is False
    )
    if user_id == acting_user_id and ("active" in values and not values["active"] or ("role" in values and values["role"] != target["role"])):
        raise DomainError(409, "self_change", "You cannot deactivate or change the role of your own account")
    if losing_superadmin and _active_superadmins(conn) <= 1:
        raise DomainError(409, "last_superadmin", "There must always be at least one active superadmin")
    if values:
        conn.execute(update(users).where(users.c.id == user_id).values(**values))
        if values.get("active") is False:
            _revoke_all(conn, user_id)  # deactivated users are signed out immediately
        conn.commit()
    return get_user(conn, user_id)


def set_password(conn: Connection, user_id: int, password: str) -> None:
    check_password_policy(password)
    get_user(conn, user_id)
    conn.execute(update(users).where(users.c.id == user_id).values(password_hash=hash_password(password)))
    _revoke_all(conn, user_id)  # a password change signs every session out
    conn.commit()


def change_own_password(conn: Connection, user_id: int, current: str, new: str) -> None:
    row = conn.execute(select(users).where(users.c.id == user_id)).first()
    if row is None or not verify_password(row.password_hash, current):
        raise DomainError(401, "invalid_credentials", "The current password is incorrect")
    set_password(conn, user_id, new)
