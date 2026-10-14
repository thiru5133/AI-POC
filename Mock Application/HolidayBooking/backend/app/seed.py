"""Seed data that cannot live in a migration because it holds a secret: the first superadmin.

Hotels, room types and rooms are seeded by the Alembic migrations. The superadmin comes from the environment
(HB_SUPERADMIN_EMAIL / HB_SUPERADMIN_PASSWORD / HB_SUPERADMIN_NAME) and is created only when no superadmin exists
yet, so restarting never resets a password that was changed later.
"""

import os

from sqlalchemy import func, select

from app import accounts, db
from app.db import users


def seed_superadmin() -> None:
    email = os.getenv("HB_SUPERADMIN_EMAIL", "").strip()
    password = os.getenv("HB_SUPERADMIN_PASSWORD", "")
    name = os.getenv("HB_SUPERADMIN_NAME", "").strip() or "Super Admin"
    with db.get_engine().connect() as conn:
        if conn.execute(select(func.count()).select_from(users).where(users.c.role == "superadmin")).scalar():
            print("Superadmin already exists: leaving users untouched", flush=True)
            return
        if not email or not password:
            print("WARNING: no superadmin exists and HB_SUPERADMIN_EMAIL / HB_SUPERADMIN_PASSWORD are not set: "
                  "nobody can log in to the admin area", flush=True)
            return
        accounts.create_user(conn, email, name, password, "superadmin")
        print(f"Seeded the superadmin {email.lower()}", flush=True)
