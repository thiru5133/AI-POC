"""Prepares the database before the API starts:

    python -m app.migrate

1. waits until SQL Server accepts connections and makes sure HolidayBooking's database exists,
2. applies the Alembic migrations (schema + the seeded hotels, room types and rooms),
3. seeds the first superadmin from HB_SUPERADMIN_* (only when no superadmin exists yet).
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

from app import db
from app.seed import seed_superadmin


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


if __name__ == "__main__":
    main()
