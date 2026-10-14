"""Booking rules: class availability, booking and cancellation across all gyms.

All times are naive UTC, like every other timestamp in the database.
"""

import os
import secrets
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select, true
from sqlalchemy.engine import Connection

from app.db import bookings, class_sessions, class_types, gyms

MAX_DAYS_AHEAD = int(os.getenv("GB_MAX_DAYS_AHEAD", "60"))


class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def validate_range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Defaults to today..today+6 and returns the (from, to) range, or raises DomainError."""
    start = date_from or _now().date()
    end = date_to or start + timedelta(days=6)
    if end < start:
        raise DomainError(422, "invalid_dates", "date_to must not be before date_from")
    if start < _now().date():
        raise DomainError(422, "invalid_dates", "date_from cannot be in the past")
    if (end - start).days > MAX_DAYS_AHEAD:
        raise DomainError(422, "invalid_dates", f"The date range is limited to {MAX_DAYS_AHEAD} days")
    return start, end


def _booked_counts(conn: Connection, session_ids: list[int]) -> dict[int, int]:
    if not session_ids:
        return {}
    return dict(
        conn.execute(
            select(bookings.c.session_id, func.count())
            .where(bookings.c.session_id.in_(session_ids), bookings.c.status == "confirmed")
            .group_by(bookings.c.session_id)
        ).all()
    )


# ---------- class sessions ----------
def list_sessions(
    conn: Connection,
    date_from: date | None = None,
    date_to: date | None = None,
    gym: str | None = None,
    city: str | None = None,
    category: str | None = None,
) -> dict:
    """Upcoming class sessions with the spots still free, only for gyms / classes that are open for booking."""
    start, end = validate_range(date_from, date_to)
    stmt = (
        select(
            class_sessions.c.id.label("session_id"),
            class_sessions.c.starts_at,
            class_sessions.c.trainer,
            class_sessions.c.capacity,
            gyms.c.code.label("gym_code"),
            gyms.c.name.label("gym_name"),
            gyms.c.city,
            gyms.c.country,
            class_types.c.code.label("class_code"),
            class_types.c.name.label("class_name"),
            class_types.c.description.label("class_description"),
            class_types.c.duration_min,
            class_types.c.price,
        )
        .select_from(
            class_sessions.join(gyms, gyms.c.code == class_sessions.c.gym_code).join(
                class_types, class_types.c.id == class_sessions.c.class_type_id
            )
        )
        .where(
            gyms.c.active == true(),
            class_types.c.active == true(),
            class_sessions.c.active == true(),
            class_sessions.c.starts_at >= max(datetime.combine(start, time.min), _now()),
            class_sessions.c.starts_at < datetime.combine(end + timedelta(days=1), time.min),
        )
        .order_by(class_sessions.c.starts_at, gyms.c.name)
    )
    if gym:
        stmt = stmt.where(gyms.c.code == gym)
    if city:
        stmt = stmt.where(func.lower(gyms.c.city) == city.strip().lower())
    if category:
        stmt = stmt.where(class_types.c.code == category)
    rows = conn.execute(stmt).all()
    if gym and not rows and conn.execute(select(gyms.c.code).where(gyms.c.code == gym)).first() is None:
        raise DomainError(404, "unknown_gym", f"Unknown gym '{gym}'")
    booked = _booked_counts(conn, [r.session_id for r in rows])
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "sessions": [
            {
                "session_id": r.session_id,
                "gym": {"code": r.gym_code, "name": r.gym_name, "city": r.city, "country": r.country},
                "class": {
                    "code": r.class_code,
                    "name": r.class_name,
                    "description": r.class_description,
                    "duration_min": r.duration_min,
                    "price": r.price,
                },
                "trainer": r.trainer,
                "starts_at": r.starts_at.isoformat(),
                "capacity": r.capacity,
                "spots_left": max(r.capacity - booked.get(r.session_id, 0), 0),
            }
            for r in rows
        ],
    }


# ---------- bookings ----------
def create_booking(conn: Connection, session_id: int, member_name: str, member_email: str) -> dict:
    email = member_email.strip().lower()
    row = conn.execute(
        select(class_sessions, gyms.c.name.label("gym_name"), gyms.c.active.label("gym_active"),
               class_types.c.code.label("class_code"), class_types.c.name.label("class_name"),
               class_types.c.price, class_types.c.active.label("class_active"))
        .select_from(
            class_sessions.join(gyms, gyms.c.code == class_sessions.c.gym_code).join(
                class_types, class_types.c.id == class_sessions.c.class_type_id
            )
        )
        .where(class_sessions.c.id == session_id)
    ).first()
    if row is None or not (row.active and row.gym_active and row.class_active):
        raise DomainError(404, "unknown_session", f"Unknown class session {session_id}")
    if row.starts_at <= _now():
        raise DomainError(422, "session_started", "That class has already started")
    if row.starts_at > _now() + timedelta(days=MAX_DAYS_AHEAD):
        raise DomainError(422, "too_far_ahead", f"Classes can only be booked {MAX_DAYS_AHEAD} days ahead")
    conn.rollback()  # end the read-only transaction opened above; the booking runs in a fresh one
    try:
        # A no-op write on the session takes its lock first, so concurrent requests for the same session queue up
        # and cannot both claim the last spot.
        conn.execute(class_sessions.update().where(class_sessions.c.id == session_id).values(capacity=row.capacity))
        already = conn.execute(
            select(func.count()).select_from(bookings).where(
                bookings.c.session_id == session_id, bookings.c.member_email == email, bookings.c.status == "confirmed"
            )
        ).scalar()
        if already:
            raise DomainError(409, "already_booked", "This email already has a booking for that class")
        taken = _booked_counts(conn, [session_id]).get(session_id, 0)
        if taken >= row.capacity:
            raise DomainError(409, "class_full", f"{row.class_name} at {row.gym_name} is full")
        reference = "GB-" + secrets.token_hex(4).upper()
        conn.execute(
            bookings.insert().values(
                reference=reference,
                gym_code=row.gym_code,
                session_id=session_id,
                class_code=row.class_code,
                class_name=row.class_name,
                starts_at=row.starts_at,
                member_name=member_name,
                member_email=email,
                price=row.price,
                status="confirmed",
                created_at=_now(),
            )
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return get_booking(conn, reference)


def _booking_query():
    return select(
        bookings,
        gyms.c.name.label("gym_name"),
        gyms.c.city.label("gym_city"),
        gyms.c.country.label("gym_country"),
    ).select_from(bookings.join(gyms, gyms.c.code == bookings.c.gym_code))


def get_booking(conn: Connection, reference: str) -> dict:
    row = conn.execute(_booking_query().where(bookings.c.reference == reference.strip().upper())).first()
    if row is None:
        raise DomainError(404, "booking_not_found", "Booking not found")
    return dict(row._mapping)


def list_bookings(
    conn: Connection,
    email: str | None = None,
    status: str | None = None,
    gym: str | None = None,
    limit: int = 200,
) -> list[dict]:
    stmt = _booking_query().order_by(bookings.c.starts_at.desc(), bookings.c.created_at.desc()).limit(limit)
    if email:
        stmt = stmt.where(bookings.c.member_email == email.strip().lower())
    if status:
        stmt = stmt.where(bookings.c.status == status)
    if gym:
        stmt = stmt.where(bookings.c.gym_code == gym)
    return [dict(r._mapping) for r in conn.execute(stmt)]


def cancel_booking(conn: Connection, reference: str) -> dict:
    booking = get_booking(conn, reference)
    if booking["status"] == "cancelled":
        raise DomainError(409, "already_cancelled", "This booking is already cancelled")
    if booking["starts_at"] <= _now():
        raise DomainError(409, "class_started", "Bookings for classes that have already started cannot be cancelled")
    conn.execute(
        bookings.update().where(bookings.c.reference == booking["reference"]).values(status="cancelled", cancelled_at=_now())
    )
    conn.commit()
    return get_booking(conn, reference)


def upcoming_booking_count(conn: Connection, **filters) -> int:
    """Confirmed bookings for classes that have not started yet, for one gym / class type / session (guards deactivation)."""
    stmt = select(func.count()).select_from(bookings).where(bookings.c.status == "confirmed", bookings.c.starts_at > _now())
    if "gym" in filters:
        stmt = stmt.where(bookings.c.gym_code == filters["gym"])
    if "session_id" in filters:
        stmt = stmt.where(bookings.c.session_id == filters["session_id"])
    if "class_type_id" in filters:
        stmt = stmt.where(
            bookings.c.session_id.in_(select(class_sessions.c.id).where(class_sessions.c.class_type_id == filters["class_type_id"]))
        )
    return conn.execute(stmt).scalar() or 0
