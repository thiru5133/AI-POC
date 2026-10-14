"""Prepares the database before the API starts:

    python -m app.migrate

1. waits until SQL Server accepts connections and makes sure GymBooking's database exists,
2. applies the Alembic migrations (schema + the seeded gyms and class types),
3. seeds the first superadmin from GB_SUPERADMIN_* (only when no superadmin exists yet),
4. tops up the demo timetable so there are always upcoming class sessions.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

from app import db
from app.seed import seed_demo_sessions, seed_superadmin


def upgrade(revision: str = "head") -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    command.upgrade(config, revision)


def main() -> None:
    if db.DATABASE_URL is None:  # an explicit URL (tests) is used as-is
        db.ensure_database()
    upgrade()
    print("Migrations applied", flush=True)
    seed_superadmin()
    seed_demo_sessions()


if __name__ == "__main__":
    main()
