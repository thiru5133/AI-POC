"""Storage on SQL Server, in HolidayBooking's own database (HB_DB_NAME). The schema and the seed data (hotels,
room types, rooms) are created by the Alembic migrations (see app/migrate.py), not by the application."""

import os
import time

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import OperationalError

# Full URL override (used by the tests with SQLite); otherwise the URL is built from the HB_DB_* settings.
DATABASE_URL: str | None = os.getenv("HB_DATABASE_URL") or None

metadata = MetaData()

hotels = Table(
    "hotels",
    metadata,
    Column("code", String(40), primary_key=True),  # URL-safe slug, e.g. "holiday-colombo"
    Column("name", String(120), nullable=False),
    Column("city", String(80), nullable=False),
    Column("country", String(80), nullable=False),
    Column("address", String(200), nullable=False, default=""),
    Column("description", String(500), nullable=False, default=""),
    Column("stars", Integer, nullable=False, default=3),
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime, nullable=False),
)
room_types = Table(
    "room_types",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("hotel_code", String(40), ForeignKey("hotels.code"), nullable=False),
    Column("code", String(30), nullable=False),
    Column("name", String(60), nullable=False),
    Column("description", String(300), nullable=False, default=""),
    Column("price_per_night", Integer, nullable=False),
    Column("max_guests", Integer, nullable=False),
    Column("active", Boolean, nullable=False, default=True),
    UniqueConstraint("hotel_code", "code", name="uq_room_types_hotel_code"),
)
rooms = Table(
    "rooms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("hotel_code", String(40), ForeignKey("hotels.code"), nullable=False),
    Column("room_type_id", Integer, ForeignKey("room_types.id"), nullable=False),
    Column("number", String(10), nullable=False),
    Column("active", Boolean, nullable=False, default=True),
    UniqueConstraint("hotel_code", "number", name="uq_rooms_hotel_number"),
)
bookings = Table(
    "bookings",
    metadata,
    Column("reference", String(20), primary_key=True),
    Column("hotel_code", String(40), ForeignKey("hotels.code"), nullable=False),
    Column("room_id", Integer, ForeignKey("rooms.id"), nullable=False),
    # snapshots: the booking stays readable even if the room is later renumbered or deactivated
    Column("room_number", String(10), nullable=False),
    Column("category_code", String(30), nullable=False),
    Column("guest_name", String(120), nullable=False),
    Column("guest_email", String(320), nullable=False, index=True),
    Column("guests", Integer, nullable=False),
    Column("check_in", Date, nullable=False),
    Column("check_out", Date, nullable=False),
    Column("nights", Integer, nullable=False),
    Column("total_price", Integer, nullable=False),
    Column("status", String(20), nullable=False, default="confirmed"),
    Column("created_at", DateTime, nullable=False),
    Column("cancelled_at", DateTime, nullable=True),
)
users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(320), nullable=False, unique=True),
    Column("name", String(120), nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("role", String(20), nullable=False),  # superadmin | admin
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime, nullable=False),
    Column("last_login_at", DateTime, nullable=True),
)
sessions = Table(
    "sessions",
    metadata,
    Column("token_hash", String(64), primary_key=True),  # sha256 of the cookie / bearer token
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("created_at", DateTime, nullable=False),
    Column("expires_at", DateTime, nullable=False),
)

_engine: Engine | None = None


def _setting(name: str, default: str) -> str:
    return os.getenv(name) or default


def _mssql_url(database: str) -> URL:
    return URL.create(
        "mssql+pyodbc",
        username=_setting("HB_DB_USER", "sa"),
        password=_setting("HB_DB_PASSWORD", ""),
        host=_setting("HB_DB_HOST", "localhost"),
        port=int(_setting("HB_DB_PORT", "1433")),
        database=database,
        query={"driver": "ODBC Driver 18 for SQL Server", "TrustServerCertificate": "yes"},
    )


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = DATABASE_URL or _mssql_url(_setting("HB_DB_NAME", "holidaybooking"))
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def ensure_database(retries: int = 40, delay: float = 3.0) -> None:
    """Waits for SQL Server, then creates the HolidayBooking database on it if it does not exist yet."""
    name = _setting("HB_DB_NAME", "holidaybooking")
    if not name.replace("_", "").isalnum():
        raise RuntimeError("HB_DB_NAME may only contain letters, digits and underscores")
    host, port = _setting("HB_DB_HOST", "localhost"), _setting("HB_DB_PORT", "1433")
    admin = create_engine(_mssql_url("master"), isolation_level="AUTOCOMMIT")
    try:
        for attempt in range(1, retries + 1):
            try:
                with admin.connect() as conn:
                    print(f"SQL Server is running at {host}:{port}", flush=True)
                    exists = conn.execute(text("SELECT DB_ID(:n)"), {"n": name}).scalar() is not None
                    if exists:
                        print(f"Database '{name}' exists", flush=True)
                    else:
                        conn.execute(text(f"CREATE DATABASE [{name}]"))
                        print(f"Database '{name}' did not exist: created it", flush=True)
                return
            except OperationalError:
                if attempt == retries:
                    raise
                print(f"Waiting for SQL Server at {host}:{port} ({attempt}/{retries})...", flush=True)
                time.sleep(delay)
    finally:
        admin.dispose()
