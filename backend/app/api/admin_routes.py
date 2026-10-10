from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api import deps
from app.api.schemas import (
    OnboardingRequestOut,
    RejectRequest,
    UserDetailOut,
    UserListOut,
    UserSummaryOut,
)
from app.auth.service import AuthService
from app.models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _out(user: User) -> OnboardingRequestOut:
    return OnboardingRequestOut(
        id=user.id,
        name=user.name,
        email=user.email,
        status=user.status,
        rejection_reason=user.rejection_reason,
        created_at=user.created_at,
        reviewed_at=user.reviewed_at,
    )


@router.get("/onboarding-requests", response_model=list[OnboardingRequestOut])
async def list_requests(
    status: Literal["pending", "active", "rejected", "disabled"] | None = "pending",
    _: User = Depends(deps.require_superadmin),
    auth: AuthService = Depends(deps.get_auth_service),
):
    return [_out(u) for u in await auth.list_requests(status)]


@router.post("/onboarding-requests/{request_id}/approve", response_model=OnboardingRequestOut)
async def approve(
    request_id: str,
    reviewer: User = Depends(deps.require_superadmin),
    auth: AuthService = Depends(deps.get_auth_service),
):
    return _out(await auth.approve(request_id, reviewer.id))


@router.post("/onboarding-requests/{request_id}/reject", response_model=OnboardingRequestOut)
async def reject(
    request_id: str,
    body: RejectRequest,
    reviewer: User = Depends(deps.require_superadmin),
    auth: AuthService = Depends(deps.get_auth_service),
):
    return _out(await auth.reject(request_id, reviewer.id, body.reason))


def _summary(user: User) -> UserSummaryOut:
    return UserSummaryOut(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        status=user.status,
        tenant_id=user.tenant_id,
        created_at=user.created_at,
    )


@router.get("/users", response_model=UserListOut)
async def list_users(
    status: Literal["pending", "active", "rejected", "disabled"] | None = None,
    role: Literal["admin", "superadmin"] | None = None,
    q: str | None = Query(default=None, max_length=100, description="Matches name or email"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(deps.require_superadmin),
    auth: AuthService = Depends(deps.get_auth_service),
):
    rows, total, counts = await auth.search_users(status, role, q, limit, offset)
    return UserListOut(items=[_summary(u) for u in rows], total=total, limit=limit, offset=offset, counts=counts)


@router.get("/users/{user_id}", response_model=UserDetailOut)
async def get_user(
    user_id: str,
    _: User = Depends(deps.require_superadmin),
    auth: AuthService = Depends(deps.get_auth_service),
):
    user, reviewed_by_name, tenant_name = await auth.user_detail(user_id)
    return UserDetailOut(
        **_summary(user).model_dump(),
        tenant_name=tenant_name,
        rejection_reason=user.rejection_reason,
        reviewed_by_name=reviewed_by_name,
        reviewed_at=user.reviewed_at,
    )
