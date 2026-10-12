"""Hotels, room types and rooms: public reads and the admin writes.

Nothing that guests have booked is ever deleted or silently changed: a hotel, room type or room with upcoming
bookings cannot be deactivated, moved or removed (409), and anything with booking history can only be deactivated.
"""

import re
from datetime import datetime, timezone

from sqlalchemy import and_, func, select, true
from sqlalchemy.engine import Connection

from app.db import bookings, hotels, room_types, rooms
from app.service import DomainError, upcoming_booking_count

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_NUMBER_RE = re.compile(r"^[A-Za-z0-9-]{1,10}$")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:40].strip("-") or "hotel"


# ---------- hotels ----------
def _hotel_stats(conn: Connection, codes: list[str]) -> dict[str, tuple[int, int | None]]:
    if not codes:
        return {}
    room_counts = dict(
        conn.execute(select(rooms.c.hotel_code, func.count()).where(rooms.c.hotel_code.in_(codes), rooms.c.active == true()).group_by(rooms.c.hotel_code)).all()
    )
    min_prices = dict(
        conn.execute(
            select(room_types.c.hotel_code, func.min(room_types.c.price_per_night))
            .where(room_types.c.hotel_code.in_(codes), room_types.c.active == true())
            .group_by(room_types.c.hotel_code)
        ).all()
    )
    return {c: (room_counts.get(c, 0), min_prices.get(c)) for c in codes}


def list_hotels(
    conn: Connection, city: str | None = None, country: str | None = None, include_inactive: bool = False
) -> list[dict]:
    stmt = select(hotels).order_by(hotels.c.country, hotels.c.city, hotels.c.name)
    if not include_inactive:
        stmt = stmt.where(hotels.c.active == true())
    if city:
        stmt = stmt.where(func.lower(hotels.c.city) == city.strip().lower())
    if country:
        stmt = stmt.where(func.lower(hotels.c.country) == country.strip().lower())
    rows = [dict(r._mapping) for r in conn.execute(stmt)]
    stats = _hotel_stats(conn, [r["code"] for r in rows])
    for row in rows:
        row["room_count"], row["from_price"] = stats[row["code"]]
    return rows


def get_hotel(conn: Connection, code: str, include_inactive: bool = False) -> dict:
    row = conn.execute(select(hotels).where(hotels.c.code == code)).first()
    if row is None or (not row.active and not include_inactive):
        raise DomainError(404, "unknown_hotel", f"Unknown hotel '{code}'")
    data = dict(row._mapping)
    data["room_count"], data["from_price"] = _hotel_stats(conn, [code])[code]
    return data


def create_hotel(conn: Connection, name: str, city: str, country: str, address: str, description: str, stars: int, code: str | None) -> dict:
    base = slugify(code or name)
    candidate, n = base, 2
    if code and conn.execute(select(hotels.c.code).where(hotels.c.code == base)).first():
        raise DomainError(409, "code_taken", f"A hotel with the code '{base}' already exists")
    while conn.execute(select(hotels.c.code).where(hotels.c.code == candidate)).first():
        candidate, n = f"{base[:36]}-{n}", n + 1
    conn.execute(
        hotels.insert().values(
            code=candidate, name=name, city=city, country=country, address=address, description=description,
            stars=stars, active=True, created_at=_now(),
        )
    )
    conn.commit()
    return get_hotel(conn, candidate, include_inactive=True)


def update_hotel(conn: Connection, code: str, changes: dict) -> dict:
    get_hotel(conn, code, include_inactive=True)
    if changes.get("active") is False and upcoming_booking_count(conn, hotel=code):
        raise DomainError(409, "has_upcoming_bookings", "This hotel has upcoming bookings: cancel them before deactivating it")
    if changes:
        conn.execute(hotels.update().where(hotels.c.code == code).values(**changes))
        conn.commit()
    return get_hotel(conn, code, include_inactive=True)


def delete_hotel(conn: Connection, code: str) -> None:
    get_hotel(conn, code, include_inactive=True)
    if conn.execute(select(func.count()).select_from(bookings).where(bookings.c.hotel_code == code)).scalar():
        raise DomainError(409, "has_bookings", "This hotel has booking history: deactivate it instead of deleting it")
    conn.execute(rooms.delete().where(rooms.c.hotel_code == code))
    conn.execute(room_types.delete().where(room_types.c.hotel_code == code))
    conn.execute(hotels.delete().where(hotels.c.code == code))
    conn.commit()


# ---------- room types ----------
def list_room_types(conn: Connection, hotel: str, include_inactive: bool = False) -> list[dict]:
    get_hotel(conn, hotel, include_inactive=include_inactive)
    stmt = select(room_types).where(room_types.c.hotel_code == hotel).order_by(room_types.c.price_per_night)
    if not include_inactive:
        stmt = stmt.where(room_types.c.active == true())
    rows = [dict(r._mapping) for r in conn.execute(stmt)]
    counts = dict(conn.execute(select(rooms.c.room_type_id, func.count()).where(rooms.c.hotel_code == hotel, rooms.c.active == true()).group_by(rooms.c.room_type_id)).all())
    for row in rows:
        row["total_rooms"] = counts.get(row["id"], 0)
    return rows


def _get_room_type(conn: Connection, type_id: int):
    row = conn.execute(select(room_types).where(room_types.c.id == type_id)).first()
    if row is None:
        raise DomainError(404, "unknown_room_type", "Room type not found")
    return row


def create_room_type(conn: Connection, hotel: str, code: str, name: str, description: str, price: int, max_guests: int) -> dict:
    get_hotel(conn, hotel, include_inactive=True)
    code = slugify(code or name)[:30]
    if conn.execute(select(room_types.c.id).where(room_types.c.hotel_code == hotel, room_types.c.code == code)).first():
        raise DomainError(409, "code_taken", f"This hotel already has a '{code}' room type")
    conn.execute(
        room_types.insert().values(
            hotel_code=hotel, code=code, name=name, description=description, price_per_night=price, max_guests=max_guests, active=True
        )
    )
    conn.commit()
    row = conn.execute(select(room_types).where(room_types.c.hotel_code == hotel, room_types.c.code == code)).first()
    return {**dict(row._mapping), "total_rooms": 0}


def update_room_type(conn: Connection, type_id: int, changes: dict) -> dict:
    row = _get_room_type(conn, type_id)
    if changes.get("active") is False and upcoming_booking_count(conn, room_type_id=type_id):
        raise DomainError(409, "has_upcoming_bookings", "This room type has upcoming bookings: cancel them first")
    if changes:  # a price change only affects future bookings: existing ones keep the total they were made with
        conn.execute(room_types.update().where(room_types.c.id == type_id).values(**changes))
        conn.commit()
    updated = {**dict(_get_room_type(conn, type_id)._mapping)}
    updated["total_rooms"] = conn.execute(
        select(func.count()).select_from(rooms).where(rooms.c.room_type_id == row.id, rooms.c.active == true())
    ).scalar() or 0
    return updated


def delete_room_type(conn: Connection, type_id: int) -> None:
    _get_room_type(conn, type_id)
    if conn.execute(select(func.count()).select_from(rooms).where(rooms.c.room_type_id == type_id)).scalar():
        raise DomainError(409, "has_rooms", "Remove or move this room type's rooms first (or deactivate the type)")
    conn.execute(room_types.delete().where(room_types.c.id == type_id))
    conn.commit()


# ---------- rooms ----------
def list_rooms(conn: Connection, hotel: str) -> list[dict]:
    get_hotel(conn, hotel, include_inactive=True)
    stmt = (
        select(rooms, room_types.c.code.label("room_type_code"), room_types.c.name.label("room_type_name"))
        .select_from(rooms.join(room_types, room_types.c.id == rooms.c.room_type_id))
        .where(rooms.c.hotel_code == hotel)
        .order_by(rooms.c.id)
    )
    return [dict(r._mapping) for r in conn.execute(stmt)]


def _get_room(conn: Connection, room_id: int):
    row = conn.execute(select(rooms).where(rooms.c.id == room_id)).first()
    if row is None:
        raise DomainError(404, "unknown_room", "Room not found")
    return row


def add_rooms(conn: Connection, hotel: str, room_type_id: int, numbers: list[str]) -> list[dict]:
    get_hotel(conn, hotel, include_inactive=True)
    type_row = _get_room_type(conn, room_type_id)
    if type_row.hotel_code != hotel:
        raise DomainError(404, "unknown_room_type", "That room type does not belong to this hotel")
    cleaned = [n.strip() for n in numbers]
    if not cleaned or len(cleaned) > 200:
        raise DomainError(422, "invalid_rooms", "Give between 1 and 200 room numbers")
    bad = [n for n in cleaned if not _NUMBER_RE.match(n)]
    if bad:
        raise DomainError(422, "invalid_rooms", f"Invalid room number(s): {', '.join(bad[:5])} (letters, digits and '-', up to 10 characters)")
    if len(set(cleaned)) != len(cleaned):
        raise DomainError(422, "invalid_rooms", "The same room number is listed twice")
    taken = list(conn.execute(select(rooms.c.number).where(rooms.c.hotel_code == hotel, rooms.c.number.in_(cleaned))).scalars())
    if taken:
        raise DomainError(409, "room_exists", f"This hotel already has room(s): {', '.join(sorted(taken)[:5])}")
    conn.execute(rooms.insert(), [{"hotel_code": hotel, "room_type_id": room_type_id, "number": n, "active": True} for n in cleaned])
    conn.commit()
    return [r for r in list_rooms(conn, hotel) if r["number"] in cleaned]


def update_room(conn: Connection, room_id: int, changes: dict) -> dict:
    room = _get_room(conn, room_id)
    new_type = changes.get("room_type_id")
    if new_type is not None and new_type != room.room_type_id:
        if _get_room_type(conn, new_type).hotel_code != room.hotel_code:
            raise DomainError(404, "unknown_room_type", "That room type does not belong to this hotel")
    moving = new_type is not None and new_type != room.room_type_id
    if (changes.get("active") is False or moving) and upcoming_booking_count(conn, room_id=room_id):
        raise DomainError(409, "has_upcoming_bookings", "This room has upcoming bookings: cancel them first")
    if changes:
        conn.execute(rooms.update().where(rooms.c.id == room_id).values(**changes))
        conn.commit()
    return next(r for r in list_rooms(conn, room.hotel_code) if r["id"] == room_id)


def delete_room(conn: Connection, room_id: int) -> None:
    _get_room(conn, room_id)
    if conn.execute(select(func.count()).select_from(bookings).where(bookings.c.room_id == room_id)).scalar():
        raise DomainError(409, "has_bookings", "This room has booking history: deactivate it instead of deleting it")
    conn.execute(rooms.delete().where(rooms.c.id == room_id))
    conn.commit()
