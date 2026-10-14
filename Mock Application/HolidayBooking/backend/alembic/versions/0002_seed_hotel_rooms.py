"""seed the hotel's fixed room categories and rooms

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"

# (code, name, description, price per night, max guests, first room number, room count)
CATEGORIES = [
    ("standard", "Standard", "Cosy room with a queen bed and city view.", 120, 2, 101, 8),
    ("deluxe", "Deluxe", "Spacious room with a king bed and a balcony.", 200, 3, 201, 6),
    ("family", "Family", "Two bedrooms with a living area, ideal for families.", 280, 5, 301, 4),
    ("suite", "Suite", "Separate lounge, king bed and a panoramic view.", 450, 4, 401, 3),
    ("presidential", "Presidential", "Top-floor suite with private terrace and butler service.", 900, 6, 501, 1),
]

categories_table = sa.table(
    "room_categories",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
    sa.column("description", sa.String),
    sa.column("price_per_night", sa.Integer),
    sa.column("max_guests", sa.Integer),
)
rooms_table = sa.table("rooms", sa.column("number", sa.Integer), sa.column("category_code", sa.String))


def upgrade() -> None:
    op.bulk_insert(
        categories_table,
        [
            {"code": c, "name": n, "description": d, "price_per_night": p, "max_guests": g}
            for c, n, d, p, g, _, _ in CATEGORIES
        ],
    )
    op.bulk_insert(
        rooms_table,
        [
            {"number": first + i, "category_code": code}
            for code, _, _, _, _, first, count in CATEGORIES
            for i in range(count)
        ],
    )


def downgrade() -> None:
    op.execute(rooms_table.delete())
    op.execute(categories_table.delete())
