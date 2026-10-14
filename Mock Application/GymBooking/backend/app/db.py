"""Storage on SQL Server, in GymBooking's own database (GB_DB_NAME). The schema and the seed data (gyms, class
types, class sessions) are created by the Alembic migrations (see app/migrate.py), not by the application."""

import os
import time

from sqlalchemy import (
    Boolean,
    Column,
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

# Full URL override (used by the tests with SQLite); otherwise the URL is built from the GB_DB_* settings.
DATABASE_URL: str | None = os.getenv("GB_DATABASE_URL") or None

metadata = MetaData()

gyms = Table(
    "gyms",
    metadata,
    Column("code", String(40), primary_key=True),  # URL-safe slug, e.g. "fitzone-colombo"
    Column("name", String(120), nullable=False),
    Column("city", String(80), nullable=False),
    Column("country", String(80), nullable=False),
    Column("address", String(200), nullable=False, default=""),
    Column("description", String(500), nullable=False, default=""),
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime, nullable=False),
)
class_types = Table(
    "class_types",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("gym_code", String(40), ForeignKey("gyms.code"), nullable=False),
    Column("code", String(30), nullable=False),
    Column("name", String(60), nullable=False),
    Column("description", String(300), nullable=False, default=""),
    Column("duration_min", Integer, nullable=False),
    Column("price", Integer, nullable=False),
    Column("active", Boolean, nullable=False, default=True),
    UniqueConstraint("gym_code", "code", name="uq_class_types_gym_code"),
)
class_sessions = Table(
    "class_sessions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("gym_code", String(40), ForeignKey("gyms.code"), nullable=False),
    Column("class_type_id", Integer, ForeignKey("class_types.id"), nullable=False),
    Column("trainer", String(80), nullable=False, default=""),
    Column("starts_at", DateTime, nullable=False, index=True),
    Column("capacity", Integer, nullable=False),
    Column("active", Boolean, nullable=False, default=True),
)
bookings = Table(
    "bookings",
    metadata,
    Column("reference", String(20), primary_key=True),
    Column("gym_code", String(40), ForeignKey("gyms.code"), nullable=False),
    Column("session_id", Integer, ForeignKey("class_sessions.id"), nullable=False),
    # snapshots: the booking stays readable even if the class is later renamed or repriced
    Column("class_code", String(30), nullable=False),
    Column("class_name", String(60), nullable=False),
    Column("starts_at", DateTime, nullable=False),
    Column("member_name", String(120), nullable=False),
    Column("member_email", String(320), nullable=False, index=True),
    Column("price", Integer, nullable=False),
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
        username=_setting("GB_DB_USER", "sa"),
        password=_setting("GB_DB_PASSWORD", ""),
        host=_setting("GB_DB_HOST", "localhost"),
        port=int(_setting("GB_DB_PORT", "1433")),
        database=database,
        query={"driver": "ODBC Driver 18 for SQL Server", "TrustServerCertificate": "yes"},
    )


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = DATABASE_URL or _mssql_url(_setting("GB_DB_NAME", "gymbooking"))
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def ensure_database(retries: int = 40, delay: float = 3.0) -> None:
    """Waits for SQL Server, then creates the GymBooking database on it if it does not exist yet."""
    name = _setting("GB_DB_NAME", "gymbooking")
    if not name.replace("_", "").isalnum():
        raise RuntimeError("GB_DB_NAME may only contain letters, digits and underscores")
    host, port = _setting("GB_DB_HOST", "localhost"), _setting("GB_DB_PORT", "1433")
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
