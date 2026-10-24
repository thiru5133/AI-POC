"""Booking rules: availability, booking and cancellation across all hotels."""

import os
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, func, select, true
from sqlalchemy.engine import Connection

from app.db import bookings, hotels, room_types, rooms

MAX_NIGHTS = int(os.getenv("HB_MAX_NIGHTS", "30"))


class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def validate_dates(check_in: date, check_out: date) -> int:
    """Returns the number of nights, or raises DomainError."""
    if check_in < date.today():
        raise DomainError(422, "invalid_dates", "Check-in cannot be in the past")
    nights = (check_out - check_in).days
    if nights < 1:
        raise DomainError(422, "invalid_dates", "Check-out must be after check-in")
    if nights > MAX_NIGHTS:
        raise DomainError(422, "invalid_dates", f"Stays are limited to {MAX_NIGHTS} nights")
    return nights


def _overlapping(check_in: date, check_out: date):
    """EXISTS(a confirmed booking of this room that overlaps the stay). Check-out day is free for the next guest."""
    return (
        select(bookings.c.reference)
        .where(
            and_(
                bookings.c.room_id == rooms.c.id,
                bookings.c.status == "confirmed",
                bookings.c.check_in < check_out,
                bookings.c.check_out > check_in,
            )
        )
        .exists()
    )


def _hotel_summary(row) -> dict:
    return {"code": row.hotel_code, "name": row.hotel_name, "city": row.city, "country": row.country, "stars": row.stars}


# ---------- availability ----------
def availability(
    conn: Connection,
    check_in: date,
    check_out: date,
    hotel: str | None = None,
    city: str | None = None,
    country: str | None = None,
    category: str | None = None,
) -> dict:
    """Free rooms per hotel and room type for a stay, only for hotels / types that are open for booking."""
    nights = validate_dates(check_in, check_out)
    stmt = (
        select(
            hotels.c.code.label("hotel_code"),
            hotels.c.name.label("hotel_name"),
            hotels.c.city,
            hotels.c.country,
            hotels.c.stars,
            room_types.c.id.label("type_id"),
            room_types.c.code.label("type_code"),
            room_types.c.name.label("type_name"),
            room_types.c.description.label("type_description"),
            room_types.c.price_per_night,
            room_types.c.max_guests,
        )
        .select_from(hotels.join(room_types, room_types.c.hotel_code == hotels.c.code))
        .where(hotels.c.active == true(), room_types.c.active == true())
        .order_by(hotels.c.country, hotels.c.city, hotels.c.name, room_types.c.price_per_night)
    )
    if hotel:
        stmt = stmt.where(hotels.c.code == hotel)
    if city:
        stmt = stmt.where(func.lower(hotels.c.city) == city.strip().lower())
    if country:
        stmt = stmt.where(func.lower(hotels.c.country) == country.strip().lower())
    if category:
        stmt = stmt.where(room_types.c.code == category)
    type_rows = conn.execute(stmt).all()
    if hotel and not type_rows and conn.execute(select(hotels.c.code).where(hotels.c.code == hotel)).first() is None:
        raise DomainError(404, "unknown_hotel", f"Unknown hotel '{hotel}'")

    ids = [r.type_id for r in type_rows]
    totals = dict(
        conn.execute(
            select(rooms.c.room_type_id, func.count()).where(rooms.c.room_type_id.in_(ids), rooms.c.active == true()).group_by(rooms.c.room_type_id)
        ).all()
    ) if ids else {}
    free = dict(
        conn.execute(
            select(rooms.c.room_type_id, func.count())
            .where(rooms.c.room_type_id.in_(ids), rooms.c.active == true(), ~_overlapping(check_in, check_out))
            .group_by(rooms.c.room_type_id)
        ).all()
    ) if ids else {}

    results: dict[str, dict] = {}
    for r in type_rows:
        entry = results.setdefault(r.hotel_code, {"hotel": _hotel_summary(r), "room_types": []})
        entry["room_types"].append(
            {
                "code": r.type_code,
                "name": r.type_name,
                "description": r.type_description,
                "price_per_night": r.price_per_night,
                "max_guests": r.max_guests,
                "total_rooms": totals.get(r.type_id, 0),
                "available_rooms": free.get(r.type_id, 0),
                "total_for_stay": r.price_per_night * nights,
            }
        )
    return {
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "nights": nights,
        "results": list(results.values()),
    }


# ---------- bookings ----------
def _free_room_ids(conn: Connection, room_type_id: int, check_in: date, check_out: date) -> list[int]:
    stmt = (
        select(rooms.c.id)
        .where(rooms.c.room_type_id == room_type_id, rooms.c.active == true(), ~_overlapping(check_in, check_out))
        .order_by(rooms.c.id)
    )
    return list(conn.execute(stmt).scalars())


def create_booking(
    conn: Connection,
    hotel: str,
    category: str,
    guest_name: str,
    guest_email: str,
    check_in: date,
    check_out: date,
    guests: int,
) -> dict:
    nights = validate_dates(check_in, check_out)
    hotel_row = conn.execute(select(hotels).where(hotels.c.code == hotel)).first()
    if hotel_row is None or not hotel_row.active:
        raise DomainError(404, "unknown_hotel", f"Unknown hotel '{hotel}'")
    type_row = conn.execute(
        select(room_types).where(room_types.c.hotel_code == hotel, room_types.c.code == category, room_types.c.active == true())
    ).first()
    if type_row is None:
        raise DomainError(404, "unknown_category", f"{hotel_row.name} has no '{category}' rooms")
    if guests > type_row.max_guests:
        raise DomainError(422, "too_many_guests", f"{type_row.name} rooms sleep at most {type_row.max_guests} guests")
    conn.rollback()  # end the read-only transaction opened above; the booking runs in a fresh one
    try:
        # A no-op write on the room type takes its lock first, so concurrent requests for the same type queue up
        # and cannot both claim the last free room.
        conn.execute(room_types.update().where(room_types.c.id == type_row.id).values(code=type_row.code))
        free = _free_room_ids(conn, type_row.id, check_in, check_out)
        if not free:
            raise DomainError(409, "sold_out", f"No {type_row.name} rooms are available at {hotel_row.name} for those dates")
        room = conn.execute(select(rooms.c.number).where(rooms.c.id == free[0])).scalar()
        reference = "HB-" + secrets.token_hex(4).upper()
        conn.execute(
            bookings.insert().values(
                reference=reference,
                hotel_code=hotel,
                room_id=free[0],
                room_number=room,
                category_code=type_row.code,
                guest_name=guest_name,
                guest_email=guest_email.lower(),
                guests=guests,
                check_in=check_in,
                check_out=check_out,
                nights=nights,
                total_price=type_row.price_per_night * nights,
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
        hotels.c.name.label("hotel_name"),
        hotels.c.city.label("hotel_city"),
        hotels.c.country.label("hotel_country"),
    ).select_from(bookings.join(hotels, hotels.c.code == bookings.c.hotel_code))


def get_booking(conn: Connection, reference: str) -> dict:
    row = conn.execute(_booking_query().where(bookings.c.reference == reference.strip().upper())).first()
    if row is None:
        raise DomainError(404, "booking_not_found", "Booking not found")
    return dict(row._mapping)


def list_bookings(
    conn: Connection,
    email: str | None = None,
    status: str | None = None,
    hotel: str | None = None,
    limit: int = 200,
    when: str | None = None,
    on: date | None = None,
    tz_offset_minutes: int = 0,
) -> list[dict]:
    """`when` narrows to one day `on` (the staff member's today): booked | check_in | check_out | staying.
    `tz_offset_minutes` is the browser's offset from UTC (as from getTimezoneOffset), since created_at is stored in UTC."""
    stmt = _booking_query().order_by(bookings.c.check_in.desc(), bookings.c.created_at.desc()).limit(limit)
    if email:
        stmt = stmt.where(bookings.c.guest_email == email.strip().lower())
    if status:
        stmt = stmt.where(bookings.c.status == status)
    if hotel:
        stmt = stmt.where(bookings.c.hotel_code == hotel)
    if when and on:
        if when == "booked":
            start = datetime(on.year, on.month, on.day) + timedelta(minutes=tz_offset_minutes)
            stmt = stmt.where(bookings.c.created_at >= start, bookings.c.created_at < start + timedelta(days=1))
        elif when == "check_in":
            stmt = stmt.where(bookings.c.check_in == on)
        elif when == "check_out":
            stmt = stmt.where(bookings.c.check_out == on)
        elif when == "staying":
            stmt = stmt.where(bookings.c.check_in <= on, bookings.c.check_out > on)
    return [dict(r._mapping) for r in conn.execute(stmt)]


def cancel_booking(conn: Connection, reference: str) -> dict:
    booking = get_booking(conn, reference)
    if booking["status"] == "cancelled":
        raise DomainError(409, "already_cancelled", "This booking is already cancelled")
    if booking["check_in"] < date.today():
        raise DomainError(409, "stay_started", "Bookings that have already started cannot be cancelled")
    conn.execute(
        bookings.update().where(bookings.c.reference == booking["reference"]).values(status="cancelled", cancelled_at=_now())
    )
    conn.commit()
    return get_booking(conn, reference)


def upcoming_booking_count(conn: Connection, **filters) -> int:
    """Confirmed bookings that have not finished yet, for one hotel / room type / room (guards deactivation)."""
    stmt = select(func.count()).select_from(bookings).where(bookings.c.status == "confirmed", bookings.c.check_out > date.today())
    if "hotel" in filters:
        stmt = stmt.where(bookings.c.hotel_code == filters["hotel"])
    if "room_id" in filters:
        stmt = stmt.where(bookings.c.room_id == filters["room_id"])
    if "room_type_id" in filters:
        stmt = stmt.where(bookings.c.room_id.in_(select(rooms.c.id).where(rooms.c.room_type_id == filters["room_type_id"])))
    return conn.execute(stmt).scalar() or 0
