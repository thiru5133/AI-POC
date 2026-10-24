"""Staff endpoints: manage hotels, room types, rooms and bookings (admin + superadmin) and users (superadmin)."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.engine import Connection

from app import accounts, catalog, service
from app.schemas import (
    HotelIn,
    HotelPatch,
    PasswordReset,
    RoomPatch,
    RoomsIn,
    RoomTypeIn,
    RoomTypePatch,
    UserIn,
    UserPatch,
)
from app.security import get_conn, require_staff, require_superadmin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_staff)])


# ---------- hotels ----------
@router.get("/hotels")
def list_hotels(conn: Connection = Depends(get_conn)):
    return catalog.list_hotels(conn, include_inactive=True)


@router.post("/hotels", status_code=201)
def create_hotel(body: HotelIn, conn: Connection = Depends(get_conn)):
    return catalog.create_hotel(conn, body.name, body.city, body.country, body.address, body.description, body.stars, body.code)


@router.patch("/hotels/{code}")
def update_hotel(code: str, body: HotelPatch, conn: Connection = Depends(get_conn)):
    return catalog.update_hotel(conn, code, body.model_dump(exclude_unset=True, exclude_none=True))


@router.delete("/hotels/{code}", status_code=204)
def delete_hotel(code: str, conn: Connection = Depends(get_conn)):
    catalog.delete_hotel(conn, code)
    return Response(status_code=204)


# ---------- room types ----------
@router.get("/hotels/{code}/room-types")
def list_room_types(code: str, conn: Connection = Depends(get_conn)):
    return catalog.list_room_types(conn, code, include_inactive=True)


@router.post("/hotels/{code}/room-types", status_code=201)
def create_room_type(code: str, body: RoomTypeIn, conn: Connection = Depends(get_conn)):
    return catalog.create_room_type(conn, code, body.code or "", body.name, body.description, body.price_per_night, body.max_guests)


@router.patch("/room-types/{type_id}")
def update_room_type(type_id: int, body: RoomTypePatch, conn: Connection = Depends(get_conn)):
    return catalog.update_room_type(conn, type_id, body.model_dump(exclude_unset=True, exclude_none=True))


@router.delete("/room-types/{type_id}", status_code=204)
def delete_room_type(type_id: int, conn: Connection = Depends(get_conn)):
    catalog.delete_room_type(conn, type_id)
    return Response(status_code=204)


# ---------- rooms ----------
@router.get("/hotels/{code}/rooms")
def list_rooms(code: str, conn: Connection = Depends(get_conn)):
    return catalog.list_rooms(conn, code)


@router.post("/hotels/{code}/rooms", status_code=201)
def add_rooms(code: str, body: RoomsIn, conn: Connection = Depends(get_conn)):
    if body.numbers is not None:
        numbers = body.numbers
    elif body.start is not None and body.count is not None:
        numbers = [str(body.start + i) for i in range(body.count)]
    else:
        raise service.DomainError(422, "invalid_rooms", "Give `numbers`, or `start` and `count`")
    return catalog.add_rooms(conn, code, body.room_type_id, numbers)


@router.patch("/rooms/{room_id}")
def update_room(room_id: int, body: RoomPatch, conn: Connection = Depends(get_conn)):
    return catalog.update_room(conn, room_id, body.model_dump(exclude_unset=True, exclude_none=True))


@router.delete("/rooms/{room_id}", status_code=204)
def delete_room(room_id: int, conn: Connection = Depends(get_conn)):
    catalog.delete_room(conn, room_id)
    return Response(status_code=204)


# ---------- bookings (staff can see and cancel any booking) ----------
@router.get("/bookings")
def list_bookings(
    hotel: str | None = None,
    status: str | None = None,
    email: str | None = None,
    when: Literal["booked", "check_in", "check_out", "staying"] | None = None,
    on: date | None = None,
    tz_offset: int = Query(default=0, ge=-840, le=840),
    conn: Connection = Depends(get_conn),
):
    return service.list_bookings(
        conn, email=email, status=status, hotel=hotel, limit=500, when=when, on=on, tz_offset_minutes=tz_offset
    )


@router.post("/bookings/{reference}/cancel")
def cancel_booking(reference: str, conn: Connection = Depends(get_conn)):
    return service.cancel_booking(conn, reference)


# ---------- users (superadmin only) ----------
@router.get("/users", dependencies=[Depends(require_superadmin)])
def list_users(conn: Connection = Depends(get_conn)):
    return accounts.list_users(conn)


@router.post("/users", status_code=201, dependencies=[Depends(require_superadmin)])
def create_user(body: UserIn, conn: Connection = Depends(get_conn)):
    return accounts.create_user(conn, body.email, body.name, body.password, body.role)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, me: dict = Depends(require_superadmin), conn: Connection = Depends(get_conn)):
    return accounts.update_user(conn, user_id, me["id"], body.name, body.role, body.active)


@router.post("/users/{user_id}/reset-password", status_code=204, dependencies=[Depends(require_superadmin)])
def reset_password(user_id: int, body: PasswordReset, conn: Connection = Depends(get_conn)):
    accounts.set_password(conn, user_id, body.password)
    return Response(status_code=204)
