"""Gyms, class types and class sessions: public reads and the admin writes.

Nothing that members have booked is ever deleted or silently changed: a gym, class type or session with upcoming
bookings cannot be deactivated, rescheduled or removed (409), and anything with booking history can only be
deactivated.
"""

import re
from datetime import datetime, timezone

from sqlalchemy import func, select, true
from sqlalchemy.engine import Connection

from app.db import bookings, class_sessions, class_types, gyms
from app.service import DomainError, upcoming_booking_count

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:40].strip("-") or "gym"


# ---------- gyms ----------
def _gym_stats(conn: Connection, codes: list[str]) -> dict[str, tuple[int, int | None]]:
    if not codes:
        return {}
    type_counts = dict(
        conn.execute(
            select(class_types.c.gym_code, func.count())
            .where(class_types.c.gym_code.in_(codes), class_types.c.active == true())
            .group_by(class_types.c.gym_code)
        ).all()
    )
    min_prices = dict(
        conn.execute(
            select(class_types.c.gym_code, func.min(class_types.c.price))
            .where(class_types.c.gym_code.in_(codes), class_types.c.active == true())
            .group_by(class_types.c.gym_code)
        ).all()
    )
    return {c: (type_counts.get(c, 0), min_prices.get(c)) for c in codes}


def list_gyms(conn: Connection, city: str | None = None, country: str | None = None, include_inactive: bool = False) -> list[dict]:
    stmt = select(gyms).order_by(gyms.c.country, gyms.c.city, gyms.c.name)
    if not include_inactive:
        stmt = stmt.where(gyms.c.active == true())
    if city:
        stmt = stmt.where(func.lower(gyms.c.city) == city.strip().lower())
    if country:
        stmt = stmt.where(func.lower(gyms.c.country) == country.strip().lower())
    rows = [dict(r._mapping) for r in conn.execute(stmt)]
    stats = _gym_stats(conn, [r["code"] for r in rows])
    for row in rows:
        row["class_type_count"], row["from_price"] = stats[row["code"]]
    return rows


def get_gym(conn: Connection, code: str, include_inactive: bool = False) -> dict:
    row = conn.execute(select(gyms).where(gyms.c.code == code)).first()
    if row is None or (not row.active and not include_inactive):
        raise DomainError(404, "unknown_gym", f"Unknown gym '{code}'")
    data = dict(row._mapping)
    data["class_type_count"], data["from_price"] = _gym_stats(conn, [code])[code]
    return data


def create_gym(conn: Connection, name: str, city: str, country: str, address: str, description: str, code: str | None) -> dict:
    base = slugify(code or name)
    candidate, n = base, 2
    if code and conn.execute(select(gyms.c.code).where(gyms.c.code == base)).first():
        raise DomainError(409, "code_taken", f"A gym with the code '{base}' already exists")
    while conn.execute(select(gyms.c.code).where(gyms.c.code == candidate)).first():
        candidate, n = f"{base[:36]}-{n}", n + 1
    conn.execute(
        gyms.insert().values(
            code=candidate, name=name, city=city, country=country, address=address, description=description,
            active=True, created_at=_now(),
        )
    )
    conn.commit()
    return get_gym(conn, candidate, include_inactive=True)


def update_gym(conn: Connection, code: str, changes: dict) -> dict:
    get_gym(conn, code, include_inactive=True)
    if changes.get("active") is False and upcoming_booking_count(conn, gym=code):
        raise DomainError(409, "has_upcoming_bookings", "This gym has upcoming bookings: cancel them before deactivating it")
    if changes:
        conn.execute(gyms.update().where(gyms.c.code == code).values(**changes))
        conn.commit()
    return get_gym(conn, code, include_inactive=True)


def delete_gym(conn: Connection, code: str) -> None:
    get_gym(conn, code, include_inactive=True)
    if conn.execute(select(func.count()).select_from(bookings).where(bookings.c.gym_code == code)).scalar():
        raise DomainError(409, "has_bookings", "This gym has booking history: deactivate it instead of deleting it")
    conn.execute(class_sessions.delete().where(class_sessions.c.gym_code == code))
    conn.execute(class_types.delete().where(class_types.c.gym_code == code))
    conn.execute(gyms.delete().where(gyms.c.code == code))
    conn.commit()


# ---------- class types ----------
def list_class_types(conn: Connection, gym: str, include_inactive: bool = False) -> list[dict]:
    get_gym(conn, gym, include_inactive=include_inactive)
    stmt = select(class_types).where(class_types.c.gym_code == gym).order_by(class_types.c.name)
    if not include_inactive:
        stmt = stmt.where(class_types.c.active == true())
    return [dict(r._mapping) for r in conn.execute(stmt)]


def _get_class_type(conn: Connection, type_id: int):
    row = conn.execute(select(class_types).where(class_types.c.id == type_id)).first()
    if row is None:
        raise DomainError(404, "unknown_class_type", "Class type not found")
    return row


def create_class_type(conn: Connection, gym: str, code: str, name: str, description: str, duration_min: int, price: int) -> dict:
    get_gym(conn, gym, include_inactive=True)
    code = slugify(code or name)[:30]
    if conn.execute(select(class_types.c.id).where(class_types.c.gym_code == gym, class_types.c.code == code)).first():
        raise DomainError(409, "code_taken", f"This gym already has a '{code}' class type")
    conn.execute(
        class_types.insert().values(
            gym_code=gym, code=code, name=name, description=description, duration_min=duration_min, price=price, active=True
        )
    )
    conn.commit()
    row = conn.execute(select(class_types).where(class_types.c.gym_code == gym, class_types.c.code == code)).first()
    return dict(row._mapping)


def update_class_type(conn: Connection, type_id: int, changes: dict) -> dict:
    _get_class_type(conn, type_id)
    if changes.get("active") is False and upcoming_booking_count(conn, class_type_id=type_id):
        raise DomainError(409, "has_upcoming_bookings", "This class type has upcoming bookings: cancel them first")
    if changes:  # a price change only affects future bookings: existing ones keep the price they were made with
        conn.execute(class_types.update().where(class_types.c.id == type_id).values(**changes))
        conn.commit()
    return dict(_get_class_type(conn, type_id)._mapping)


def delete_class_type(conn: Connection, type_id: int) -> None:
    _get_class_type(conn, type_id)
    if conn.execute(select(func.count()).select_from(class_sessions).where(class_sessions.c.class_type_id == type_id)).scalar():
        raise DomainError(409, "has_sessions", "Remove this class type's sessions first (or deactivate the type)")
    conn.execute(class_types.delete().where(class_types.c.id == type_id))
    conn.commit()


# ---------- class sessions ----------
def _session_rows(conn: Connection, where) -> list[dict]:
    booked = (
        select(bookings.c.session_id, func.count().label("booked"))
        .where(bookings.c.status == "confirmed")
        .group_by(bookings.c.session_id)
        .subquery()
    )
    stmt = (
        select(
            class_sessions,
            class_types.c.code.label("class_code"),
            class_types.c.name.label("class_name"),
            func.coalesce(booked.c.booked, 0).label("booked"),
        )
        .select_from(
            class_sessions.join(class_types, class_types.c.id == class_sessions.c.class_type_id).outerjoin(
                booked, booked.c.session_id == class_sessions.c.id
            )
        )
        .where(where)
        .order_by(class_sessions.c.starts_at)
    )
    return [dict(r._mapping) for r in conn.execute(stmt)]


def list_class_sessions(conn: Connection, gym: str) -> list[dict]:
    get_gym(conn, gym, include_inactive=True)
    return _session_rows(conn, class_sessions.c.gym_code == gym)


def _get_session(conn: Connection, session_id: int):
    row = conn.execute(select(class_sessions).where(class_sessions.c.id == session_id)).first()
    if row is None:
        raise DomainError(404, "unknown_session", "Class session not found")
    return row


def add_session(conn: Connection, gym: str, class_type_id: int, starts_at: datetime, capacity: int, trainer: str) -> dict:
    get_gym(conn, gym, include_inactive=True)
    if _get_class_type(conn, class_type_id).gym_code != gym:
        raise DomainError(404, "unknown_class_type", "That class type does not belong to this gym")
    if starts_at <= _now():
        raise DomainError(422, "invalid_time", "A session must start in the future (UTC)")
    result = conn.execute(
        class_sessions.insert().values(
            gym_code=gym, class_type_id=class_type_id, trainer=trainer.strip(), starts_at=starts_at, capacity=capacity, active=True
        )
    )
    conn.commit()
    return _session_rows(conn, class_sessions.c.id == result.inserted_primary_key[0])[0]


def update_session(conn: Connection, session_id: int, changes: dict) -> dict:
    session = _get_session(conn, session_id)
    booked = upcoming_booking_count(conn, session_id=session_id)
    if booked and (changes.get("active") is False or ("starts_at" in changes and changes["starts_at"] != session.starts_at)):
        raise DomainError(409, "has_upcoming_bookings", "This session has bookings: cancel them before rescheduling or deactivating it")
    if "capacity" in changes and changes["capacity"] < booked:
        raise DomainError(409, "capacity_too_low", f"{booked} spots are already booked")
    if "starts_at" in changes and changes["starts_at"] <= _now():
        raise DomainError(422, "invalid_time", "A session must start in the future (UTC)")
    if changes:
        conn.execute(class_sessions.update().where(class_sessions.c.id == session_id).values(**changes))
        conn.commit()
    return _session_rows(conn, class_sessions.c.id == session_id)[0]


def delete_session(conn: Connection, session_id: int) -> None:
    _get_session(conn, session_id)
    if conn.execute(select(func.count()).select_from(bookings).where(bookings.c.session_id == session_id)).scalar():
        raise DomainError(409, "has_bookings", "This session has booking history: deactivate it instead of deleting it")
    conn.execute(class_sessions.delete().where(class_sessions.c.id == session_id))
    conn.commit()
