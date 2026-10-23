"""Guest-facing endpoints: browse hotels, check availability, book, look up and cancel bookings."""

import os
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.engine import Connection

from app import catalog, service
from app.schemas import BookingRequest
from app.security import get_conn

router = APIRouter(tags=["guest"])


@router.get("/contact")
def contact():
    """The reservations phone number guests can call (HB_RESERVATIONS_PHONE); null when none is configured."""
    return {"reservations_phone": os.getenv("HB_RESERVATIONS_PHONE", "").strip() or None}


@router.get("/hotels")
def hotels(city: str | None = None, country: str | None = None, conn: Connection = Depends(get_conn)):
    return catalog.list_hotels(conn, city=city, country=country)


@router.get("/hotels/{code}")
def hotel(code: str, conn: Connection = Depends(get_conn)):
    return {**catalog.get_hotel(conn, code), "room_types": catalog.list_room_types(conn, code)}


@router.get("/availability")
def availability(
    check_in: date,
    check_out: date,
    hotel: str | None = None,
    city: str | None = None,
    country: str | None = None,
    category: str | None = None,
    conn: Connection = Depends(get_conn),
):
    return service.availability(conn, check_in, check_out, hotel=hotel, city=city, country=country, category=category)


@router.post("/bookings", status_code=201)
def create_booking(body: BookingRequest, conn: Connection = Depends(get_conn)):
    return service.create_booking(
        conn, body.hotel, body.category, body.guest_name, body.guest_email, body.check_in, body.check_out, body.guests
    )


@router.get("/bookings")
def list_bookings(
    email: str | None = None, status: str | None = None, hotel: str | None = None, conn: Connection = Depends(get_conn)
):
    return service.list_bookings(conn, email=email, status=status, hotel=hotel)


@router.get("/bookings/{reference}")
def get_booking(reference: str, conn: Connection = Depends(get_conn)):
    return service.get_booking(conn, reference)


@router.post("/bookings/{reference}/cancel")
def cancel_booking(reference: str, conn: Connection = Depends(get_conn)):
    return service.cancel_booking(conn, reference)
