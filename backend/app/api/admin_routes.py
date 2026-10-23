from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api import deps
from app.api.schemas import (
    BusinessCreate,
    BusinessOut,
    BusinessPublicOut,
    BusinessUpdate,
    DomainNumberOut,
    DomainOut,
    PhoneUpdate,
    UserDetailOut,
    UserListOut,
    UserSummaryOut,
)
from app.auth.service import AuthService
from app.models import User
from app.tenants.service import BusinessService

router = APIRouter(prefix="/api/superadmin", tags=["superadmin"])
public_router = APIRouter(prefix="/api/businesses", tags=["businesses"])


# ---- businesses (tenants) ----
@router.post("/businesses", response_model=BusinessOut, status_code=201)
async def create_business(
    body: BusinessCreate,
    _: User = Depends(deps.require_superadmin),
    service: BusinessService = Depends(deps.get_business_service),
):
    """Creates the business and its admin account; the admin's password is emailed to them."""
    return await service.create(body.name, body.admin_name, body.admin_email, body.domain_id)


@router.get("/businesses", response_model=list[BusinessOut])
async def list_businesses(
    q: str | None = Query(default=None, max_length=100),
    _: User = Depends(deps.require_superadmin),
    service: BusinessService = Depends(deps.get_business_service),
):
    return await service.list_all(q)


@router.patch("/businesses/{business_id}", response_model=BusinessOut)
async def update_business(
    business_id: str,
    body: BusinessUpdate,
    _: User = Depends(deps.require_superadmin),
    service: BusinessService = Depends(deps.get_business_service),
):
    return await service.set_active(business_id, body.is_active)


# ---- the shared phone line of each domain (its compare-all assistant has no admin, so a superadmin sets it) ----
@router.get("/domain-numbers", response_model=list[DomainNumberOut])
async def list_domain_numbers(
    _: User = Depends(deps.require_superadmin),
    service: BusinessService = Depends(deps.get_business_service),
):
    return await service.domain_numbers()


@router.put("/domain-numbers/{domain_id}", response_model=DomainNumberOut)
async def set_domain_number(
    domain_id: str,
    body: PhoneUpdate,
    _: User = Depends(deps.require_superadmin),
    service: BusinessService = Depends(deps.get_business_service),
):
    """Sets (or, with a null number, clears) the number that reaches this domain's compare-all assistant."""
    return await service.set_domain_number(domain_id, body.number, body.transfer_number)


@public_router.get("/domains", response_model=list[DomainOut])
async def list_domains(
    _: User = Depends(deps.get_current_user),
    service: BusinessService = Depends(deps.get_business_service),
):
    """The domains (hotel, school, hospital, ...) a business can be created under."""
    return await service.list_domains()


@public_router.get("", response_model=list[BusinessPublicOut])
async def list_active_businesses(
    _: User = Depends(deps.get_current_user),
    service: BusinessService = Depends(deps.get_business_service),
):
    """The businesses a customer can talk to."""
    return await service.list_public()


# ---- users ----
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
    role: Literal["admin", "superadmin", "user"] | None = None,
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
    user, tenant_name = await auth.user_detail(user_id)
    return UserDetailOut(**_summary(user).model_dump(), tenant_name=tenant_name)
