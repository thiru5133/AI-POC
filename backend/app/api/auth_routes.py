from fastapi import APIRouter, Cookie, Depends, Request, Response

from app.api import deps
from app.api.schemas import LoginRequest, LoginResponse, RegisterRequest, RegisterResponse, UserOut
from app.auth.service import AuthService
from app.core.config import Settings, get_settings
from app.core.errors import UnauthorizedError
from app.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/api/auth"


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, name=user.name, email=user.email, role=user.role, status=user.status, tenant_id=user.tenant_id
    )


def _set_refresh_cookie(response: Response, raw: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path=REFRESH_COOKIE_PATH,
    )


@router.post("/register", response_model=RegisterResponse, status_code=202)
async def register(body: RegisterRequest, auth: AuthService = Depends(deps.get_auth_service)):
    await auth.register(body.name, body.email, body.organization_name)
    return RegisterResponse()


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    auth: AuthService = Depends(deps.get_auth_service),
    settings: Settings = Depends(get_settings),
):
    client = request.client.host if request.client else "unknown"
    user, access, raw = await auth.login(body.identifier, body.password, client)
    _set_refresh_cookie(response, raw, settings)
    return LoginResponse(access_token=access, user=_user_out(user))


@router.post("/refresh", response_model=LoginResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    auth: AuthService = Depends(deps.get_auth_service),
    settings: Settings = Depends(get_settings),
):
    if not refresh_token:
        raise UnauthorizedError("No session")
    user, access, raw = await auth.refresh(refresh_token)
    _set_refresh_cookie(response, raw, settings)
    return LoginResponse(access_token=access, user=_user_out(user))


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    auth: AuthService = Depends(deps.get_auth_service),
):
    if refresh_token:
        await auth.logout(refresh_token)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(deps.get_current_user)):
    return _user_out(user)
