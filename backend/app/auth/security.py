import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings
from app.core.errors import UnauthorizedError

_hasher = PasswordHasher()
# Verified against when the email is unknown so login timing does not reveal which emails exist.
DUMMY_HASH = _hasher.hash("not-a-real-password")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, like the models


# No 0/O/1/l/I so a password read from an email cannot be mistyped.
_PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_password(length: int = 14) -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(settings: Settings, user_id: str, role: str, tenant_id: str | None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "tid": tenant_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        raise UnauthorizedError("Invalid or expired token") from None


def new_refresh_token() -> tuple[str, str]:
    """Returns (raw token for the cookie, sha256 hash for the DB)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
