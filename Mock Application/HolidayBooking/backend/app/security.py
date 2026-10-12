"""Access control: the API key (every route) and staff login sessions (admin routes)."""

import hmac
import os
from collections.abc import Iterator
from typing import Any

from fastapi import Depends, Header, Request
from sqlalchemy.engine import Connection

from app import accounts, db
from app.service import DomainError

SESSION_COOKIE = "hb_session"


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Fails closed: with no HB_BACKEND_API_KEY configured every request is refused."""
    expected = os.getenv("HB_BACKEND_API_KEY", "")
    if not expected or not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise DomainError(401, "unauthorized", "A valid API key is required (X-API-Key header)")


def get_conn() -> Iterator[Connection]:
    conn = db.get_engine().connect()
    try:
        yield conn
    finally:
        conn.close()


def session_token(request: Request) -> str | None:
    """The login session token: httpOnly cookie (browser) or `Authorization: Bearer` (API clients)."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(SESSION_COOKIE)


def current_user(request: Request, conn: Connection = Depends(get_conn)) -> dict[str, Any]:
    user = accounts.user_for_token(conn, session_token(request))
    if user is None:
        raise DomainError(401, "login_required", "Please log in")
    return user


def require_staff(user: dict = Depends(current_user)) -> dict:
    return user  # any active account (admin or superadmin)


def require_superadmin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "superadmin":
        raise DomainError(403, "forbidden", "Only a superadmin can do that")
    return user
