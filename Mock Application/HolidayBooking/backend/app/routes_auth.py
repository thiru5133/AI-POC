"""Staff login. The session is an httpOnly, SameSite=Strict cookie (also accepted as a Bearer token)."""

import os

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.engine import Connection

from app import accounts
from app.schemas import ChangePasswordRequest, LoginRequest
from app.security import SESSION_COOKIE, current_user, get_conn, session_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_secure() -> bool:
    return os.getenv("HB_COOKIE_SECURE", "false").lower() == "true"


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, conn: Connection = Depends(get_conn)):
    client = request.client.host if request.client else "unknown"
    user, token = accounts.login(conn, body.email, body.password, client)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=accounts.SESSION_HOURS * 3600, httponly=True, samesite="strict",
        secure=_cookie_secure(), path="/",
    )
    return {"user": user, "token": token}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, conn: Connection = Depends(get_conn)):
    accounts.logout(conn, session_token(request))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return user


@router.post("/change-password", status_code=204)
def change_password(
    body: ChangePasswordRequest, response: Response, user: dict = Depends(current_user), conn: Connection = Depends(get_conn)
):
    accounts.change_own_password(conn, user["id"], body.current_password, body.new_password)
    response.delete_cookie(SESSION_COOKIE, path="/")  # every session was revoked: log in again
