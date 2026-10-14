"""room categories, rooms and bookings

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "room_categories",
        sa.Column("code", sa.String(30), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("price_per_night", sa.Integer, nullable=False),
        sa.Column("max_guests", sa.Integer, nullable=False),
    )
    op.create_table(
        "rooms",
        sa.Column("number", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("category_code", sa.String(30), sa.ForeignKey("room_categories.code"), nullable=False),
    )
    op.create_table(
        "bookings",
        sa.Column("reference", sa.String(20), primary_key=True),
        sa.Column("room_number", sa.Integer, sa.ForeignKey("rooms.number"), nullable=False),
        sa.Column("category_code", sa.String(30), sa.ForeignKey("room_categories.code"), nullable=False),
        sa.Column("guest_name", sa.String(120), nullable=False),
        sa.Column("guest_email", sa.String(320), nullable=False),
        sa.Column("guests", sa.Integer, nullable=False),
        sa.Column("check_in", sa.Date, nullable=False),
        sa.Column("check_out", sa.Date, nullable=False),
        sa.Column("nights", sa.Integer, nullable=False),
        sa.Column("total_price", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("cancelled_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_bookings_guest_email", "bookings", ["guest_email"])
    op.create_index("ix_bookings_room_dates", "bookings", ["room_number", "check_in", "check_out"])


def downgrade() -> None:
    op.drop_table("bookings")
    op.drop_table("rooms")
    op.drop_table("room_categories")
