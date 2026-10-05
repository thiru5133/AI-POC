"""Create the application database on SQL Server if it does not exist (retries until server is up)."""

import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def main() -> None:
    url = make_url(get_settings().database_url)
    if not url.drivername.startswith("mssql"):
        return
    db_name = url.database
    engine = create_engine(url.set(database="master"), isolation_level="AUTOCOMMIT")
    for attempt in range(30):
        try:
            with engine.connect() as conn:
                conn.execute(text(f"IF DB_ID('{db_name}') IS NULL CREATE DATABASE [{db_name}]"))
            print(f"database '{db_name}' ready")
            return
        except Exception as exc:  # server still starting
            print(f"waiting for SQL Server ({attempt + 1}/30): {exc.__class__.__name__}")
            time.sleep(3)
    raise SystemExit("SQL Server did not become available")


if __name__ == "__main__":
    main()
