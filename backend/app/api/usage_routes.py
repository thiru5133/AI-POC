from collections.abc import Callable
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import usage
from app.api import deps
from app.api.schemas import UsageOut
from app.models import User
from app.models.entities import _now
from app.repositories.usage import UsageRepository

router = APIRouter(prefix="/api/org/usage", tags=["usage"])


@router.get("", response_model=UsageOut)
async def get_usage(
    days: int = Query(30, ge=1, le=366),
    user: User = Depends(deps.require_admin),
    sessions: Callable[[], Session] = Depends(deps.get_sessions),
):
    """The admin's own business's metered usage over the last `days` days."""
    tenant_id = deps.require_tenant(user)
    since = _now() - timedelta(days=days)
    with sessions() as session:
        totals = UsageRepository(session, tenant_id).totals(since)
    return UsageOut(
        period_days=days,
        since=since,
        conversations=totals[usage.CONVERSATION],
        messages=totals[usage.MESSAGE],
        voice_minutes=round(totals[usage.VOICE_SECONDS] / 60, 1),
        tool_calls=totals[usage.TOOL_CALL],
        bookings=totals[usage.BOOKING],
        confirmations=totals[usage.CONFIRMATION],
    )
