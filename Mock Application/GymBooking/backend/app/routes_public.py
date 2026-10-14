"""Member-facing endpoints: browse gyms, list class sessions, book, look up and cancel bookings."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.engine import Connection

from app import catalog, service
from app.schemas import BookingRequest
from app.security import get_conn

router = APIRouter(tags=["member"])


@router.get("/gyms")
def gyms(city: str | None = None, country: str | None = None, conn: Connection = Depends(get_conn)):
    return catalog.list_gyms(conn, city=city, country=country)


@router.get("/gyms/{code}")
def gym(code: str, conn: Connection = Depends(get_conn)):
    return {**catalog.get_gym(conn, code), "class_types": catalog.list_class_types(conn, code)}


@router.get("/sessions")
def sessions(
    date_from: date | None = None,
    date_to: date | None = None,
    gym: str | None = None,
    city: str | None = None,
    category: str | None = None,
    conn: Connection = Depends(get_conn),
):
    return service.list_sessions(conn, date_from, date_to, gym=gym, city=city, category=category)


@router.post("/bookings", status_code=201)
def create_booking(body: BookingRequest, conn: Connection = Depends(get_conn)):
    return service.create_booking(conn, body.session_id, body.member_name, body.member_email)


@router.get("/bookings")
def list_bookings(
    email: str | None = None, status: str | None = None, gym: str | None = None, conn: Connection = Depends(get_conn)
):
    return service.list_bookings(conn, email=email, status=status, gym=gym)


@router.get("/bookings/{reference}")
def get_booking(reference: str, conn: Connection = Depends(get_conn)):
    return service.get_booking(conn, reference)


@router.post("/bookings/{reference}/cancel")
def cancel_booking(reference: str, conn: Connection = Depends(get_conn)):
    return service.cancel_booking(conn, reference)
