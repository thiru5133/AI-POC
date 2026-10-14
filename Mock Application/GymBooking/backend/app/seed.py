"""Seed data that cannot live in a migration because it holds a secret: the first superadmin.

Gyms, class types and sessions are seeded by the Alembic migrations. The superadmin comes from the environment
(GB_SUPERADMIN_EMAIL / GB_SUPERADMIN_PASSWORD / GB_SUPERADMIN_NAME) and is created only when no superadmin exists
yet, so restarting never resets a password that was changed later.
"""

import os
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select, true

from app import accounts, db
from app.db import class_sessions, class_types, users

DEMO_DAYS = 14
# class type code -> (start hour UTC, trainer, capacity); every class type runs once a day at that time
DEMO_SLOTS = {
    "yoga": (7, "Anika Perera", 12),
    "pilates": (8, "Maya Fernando", 10),
    "strength": (9, "Ravi Kumar", 10),
    "zumba": (17, "Sofia Diaz", 20),
    "hiit": (18, "Marcus Lee", 15),
    "spin": (19, "Nadia Hassan", 14),
    "boxing": (20, "Omar Siddiq", 12),
}


def seed_superadmin() -> None:
    email = os.getenv("GB_SUPERADMIN_EMAIL", "").strip()
    password = os.getenv("GB_SUPERADMIN_PASSWORD", "")
    name = os.getenv("GB_SUPERADMIN_NAME", "").strip() or "Super Admin"
    with db.get_engine().connect() as conn:
        if conn.execute(select(func.count()).select_from(users).where(users.c.role == "superadmin")).scalar():
            print("Superadmin already exists: leaving users untouched", flush=True)
            return
        if not email or not password:
            print("WARNING: no superadmin exists and GB_SUPERADMIN_EMAIL / GB_SUPERADMIN_PASSWORD are not set: "
                  "nobody can log in to the admin area", flush=True)
            return
        accounts.create_user(conn, email, name, password, "superadmin")
        print(f"Seeded the superadmin {email.lower()}", flush=True)


def seed_demo_sessions(days: int = DEMO_DAYS) -> int:
    """Tops up the demo timetable: one session per class type and day for the next `days` days (UTC).

    Idempotent (an existing session at the same class type and start time is left alone), so it runs at every start
    and the demo never runs out of upcoming classes. Class types with a code that is not in DEMO_SLOTS are skipped.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    created = 0
    with db.get_engine().connect() as conn:
        types = conn.execute(select(class_types.c.id, class_types.c.gym_code, class_types.c.code).where(class_types.c.active == true())).all()
        existing = {(r.class_type_id, r.starts_at) for r in conn.execute(select(class_sessions.c.class_type_id, class_sessions.c.starts_at))}
        rows = []
        for t in types:
            slot = DEMO_SLOTS.get(t.code)
            if slot is None:
                continue
            hour, trainer, capacity = slot
            for offset in range(days + 1):
                starts = datetime.combine(now.date() + timedelta(days=offset), time(hour))
                if starts > now and (t.id, starts) not in existing:
                    rows.append(
                        {"gym_code": t.gym_code, "class_type_id": t.id, "trainer": trainer, "starts_at": starts, "capacity": capacity, "active": True}
                    )
        if rows:
            conn.execute(class_sessions.insert(), rows)
            conn.commit()
            created = len(rows)
    print(f"Demo timetable: {created} new class sessions", flush=True)
    return created
