"""seed the demo gyms and their class types

Class sessions are not seeded here (they are dated): app/seed.py tops them up at every start.
Users are not seeded either (passwords must not live in source control): see app/seed.py.

Revision ID: 0002
Revises: 0001
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"

# code, name, city, country, address, description, class types
# class type: code, name, description, duration (min), price (INR)
GYMS = [
    (
        "fitzone-anna-nagar", "FitZone Anna Nagar", "Chennai", "India", "2nd Avenue, Anna Nagar, Chennai 600040",
        "Flagship club with a full strength floor, studios and a rooftop yoga deck.",
        [
            ("yoga", "Yoga Flow", "Gentle vinyasa flow for all levels.", 60, 300),
            ("hiit", "HIIT Blast", "High-intensity intervals, 45 minutes of work.", 45, 400),
            ("spin", "Spin Cycle", "Indoor cycling with a rhythm-based playlist.", 45, 450),
            ("zumba", "Zumba Party", "Dance fitness set to Latin beats.", 60, 350),
            ("strength", "Strength Basics", "Coached barbell and dumbbell fundamentals.", 60, 500),
        ],
    ),
    (
        "fitzone-t-nagar", "FitZone T Nagar", "Chennai", "India", "Usman Road, T Nagar, Chennai 600017",
        "Busy shopping-district club with early-morning and after-work classes.",
        [
            ("yoga", "Yoga Flow", "Gentle vinyasa flow for all levels.", 60, 300),
            ("zumba", "Zumba Party", "Dance fitness set to Latin beats.", 60, 350),
            ("hiit", "HIIT Blast", "High-intensity intervals, 45 minutes of work.", 45, 400),
            ("strength", "Strength Basics", "Coached barbell and dumbbell fundamentals.", 60, 500),
        ],
    ),
    (
        "fitzone-adyar", "FitZone Adyar", "Chennai", "India", "Lattice Bridge Road, Adyar, Chennai 600020",
        "Calm neighbourhood club near the river with friendly small-group classes.",
        [
            ("yoga", "Yoga Flow", "Gentle vinyasa flow for all levels.", 60, 250),
            ("pilates", "Mat Pilates", "Core-focused mat work for posture and mobility.", 50, 350),
            ("hiit", "HIIT Blast", "High-intensity intervals, 45 minutes of work.", 45, 350),
        ],
    ),
    (
        "fitzone-velachery", "FitZone Velachery", "Chennai", "India", "100 Feet Road, Velachery, Chennai 600042",
        "Large IT-corridor club open late, with a boxing ring and spin studio.",
        [
            ("yoga", "Yoga Flow", "Gentle vinyasa flow for all levels.", 60, 300),
            ("hiit", "HIIT Blast", "High-intensity intervals, 45 minutes of work.", 45, 450),
            ("spin", "Spin Cycle", "Indoor cycling with a rhythm-based playlist.", 45, 450),
            ("boxing", "Boxing Fit", "Pad work and bag drills, no contact.", 60, 600),
        ],
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    gyms = sa.table(
        "gyms",
        sa.column("code", sa.String), sa.column("name", sa.String), sa.column("city", sa.String),
        sa.column("country", sa.String), sa.column("address", sa.String), sa.column("description", sa.String),
        sa.column("active", sa.Boolean), sa.column("created_at", sa.DateTime),
    )
    class_types = sa.table(
        "class_types",
        sa.column("gym_code", sa.String), sa.column("code", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.String), sa.column("duration_min", sa.Integer), sa.column("price", sa.Integer),
        sa.column("active", sa.Boolean),
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    for code, name, city, country, address, description, types in GYMS:
        bind.execute(
            gyms.insert().values(
                code=code, name=name, city=city, country=country, address=address, description=description,
                active=True, created_at=now,
            )
        )
        bind.execute(
            class_types.insert(),
            [
                {"gym_code": code, "code": c, "name": n, "description": d, "duration_min": m, "price": p, "active": True}
                for c, n, d, m, p in types
            ],
        )


def downgrade() -> None:
    op.execute("DELETE FROM class_types")
    op.execute("DELETE FROM gyms")
