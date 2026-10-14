"""Staff endpoints: manage gyms, class types, class sessions and bookings (admin + superadmin) and users (superadmin)."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.engine import Connection

from app import accounts, catalog, service
from app.schemas import (
    ClassTypeIn,
    ClassTypePatch,
    GymIn,
    GymPatch,
    PasswordReset,
    SessionIn,
    SessionPatch,
    UserIn,
    UserPatch,
)
from app.security import get_conn, require_staff, require_superadmin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_staff)])


# ---------- gyms ----------
@router.get("/gyms")
def list_gyms(conn: Connection = Depends(get_conn)):
    return catalog.list_gyms(conn, include_inactive=True)


@router.post("/gyms", status_code=201)
def create_gym(body: GymIn, conn: Connection = Depends(get_conn)):
    return catalog.create_gym(conn, body.name, body.city, body.country, body.address, body.description, body.code)


@router.patch("/gyms/{code}")
def update_gym(code: str, body: GymPatch, conn: Connection = Depends(get_conn)):
    return catalog.update_gym(conn, code, body.model_dump(exclude_unset=True, exclude_none=True))


@router.delete("/gyms/{code}", status_code=204)
def delete_gym(code: str, conn: Connection = Depends(get_conn)):
    catalog.delete_gym(conn, code)
    return Response(status_code=204)


# ---------- class types ----------
@router.get("/gyms/{code}/class-types")
def list_class_types(code: str, conn: Connection = Depends(get_conn)):
    return catalog.list_class_types(conn, code, include_inactive=True)


@router.post("/gyms/{code}/class-types", status_code=201)
def create_class_type(code: str, body: ClassTypeIn, conn: Connection = Depends(get_conn)):
    return catalog.create_class_type(conn, code, body.code or "", body.name, body.description, body.duration_min, body.price)


@router.patch("/class-types/{type_id}")
def update_class_type(type_id: int, body: ClassTypePatch, conn: Connection = Depends(get_conn)):
    return catalog.update_class_type(conn, type_id, body.model_dump(exclude_unset=True, exclude_none=True))


@router.delete("/class-types/{type_id}", status_code=204)
def delete_class_type(type_id: int, conn: Connection = Depends(get_conn)):
    catalog.delete_class_type(conn, type_id)
    return Response(status_code=204)


# ---------- class sessions ----------
@router.get("/gyms/{code}/sessions")
def list_sessions(code: str, conn: Connection = Depends(get_conn)):
    return catalog.list_class_sessions(conn, code)


@router.post("/gyms/{code}/sessions", status_code=201)
def add_session(code: str, body: SessionIn, conn: Connection = Depends(get_conn)):
    return catalog.add_session(conn, code, body.class_type_id, body.starts_at, body.capacity, body.trainer)


@router.patch("/sessions/{session_id}")
def update_session(session_id: int, body: SessionPatch, conn: Connection = Depends(get_conn)):
    return catalog.update_session(conn, session_id, body.model_dump(exclude_unset=True, exclude_none=True))


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: int, conn: Connection = Depends(get_conn)):
    catalog.delete_session(conn, session_id)
    return Response(status_code=204)


# ---------- bookings (staff can see and cancel any booking) ----------
@router.get("/bookings")
def list_bookings(
    gym: str | None = None, status: str | None = None, email: str | None = None, conn: Connection = Depends(get_conn)
):
    return service.list_bookings(conn, email=email, status=status, gym=gym, limit=500)


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
