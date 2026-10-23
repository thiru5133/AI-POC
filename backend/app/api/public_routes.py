from fastapi import APIRouter, Depends, Request

from app.api import deps
from app.api.schemas import PublicNumberOut
from app.auth.ratelimit import public_limiter
from app.core.errors import NotFoundError
from app.tenants.service import BusinessService

router = APIRouter(prefix="/api/public", tags=["public"])


def _limit(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    public_limiter.check(key)
    public_limiter.record_failure(key)  # counts every request, see ratelimit.py


async def _numbers(service: BusinessService) -> list[dict]:
    """Active businesses (and compare-all lines that are on offer) that have a number to call."""
    return [b for b in await service.list_public() if b.get("phone")]


@router.get("/businesses", response_model=list[PublicNumberOut])
async def public_numbers(
    request: Request,
    service: BusinessService = Depends(deps.get_business_service),
):
    """No login: who customers can phone. Names and numbers only."""
    _limit(request)
    return await _numbers(service)


@router.get("/businesses/{business_id}", response_model=PublicNumberOut)
async def public_number(
    business_id: str,
    request: Request,
    service: BusinessService = Depends(deps.get_business_service),
):
    _limit(request)
    for b in await _numbers(service):
        if b["id"] == business_id:
            return b
    raise NotFoundError("No phone number for that business")
