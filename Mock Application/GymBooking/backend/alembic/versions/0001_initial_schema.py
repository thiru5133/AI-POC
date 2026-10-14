"""initial schema: gyms, class types, class sessions, bookings, users and sessions

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "gyms",
        sa.Column("code", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("country", sa.String(80), nullable=False),
        sa.Column("address", sa.String(200), nullable=False, server_default=""),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "class_types",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("gym_code", sa.String(40), sa.ForeignKey("gyms.code"), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.Column("duration_min", sa.Integer, nullable=False),
        sa.Column("price", sa.Integer, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("gym_code", "code", name="uq_class_types_gym_code"),
    )
    op.create_table(
        "class_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("gym_code", sa.String(40), sa.ForeignKey("gyms.code"), nullable=False),
        sa.Column("class_type_id", sa.Integer, sa.ForeignKey("class_types.id"), nullable=False),
        sa.Column("trainer", sa.String(80), nullable=False, server_default=""),
        sa.Column("starts_at", sa.DateTime, nullable=False),
        sa.Column("capacity", sa.Integer, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_class_sessions_starts_at", "class_sessions", ["starts_at"])
    op.create_table(
        "bookings",
        sa.Column("reference", sa.String(20), primary_key=True),
        sa.Column("gym_code", sa.String(40), sa.ForeignKey("gyms.code"), nullable=False),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("class_sessions.id"), nullable=False),
        sa.Column("class_code", sa.String(30), nullable=False),
        sa.Column("class_name", sa.String(60), nullable=False),
        sa.Column("starts_at", sa.DateTime, nullable=False),
        sa.Column("member_name", sa.String(120), nullable=False),
        sa.Column("member_email", sa.String(320), nullable=False),
        sa.Column("price", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="confirmed"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("cancelled_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_bookings_member_email", "bookings", ["member_email"])
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_login_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])


def downgrade() -> None:
    for table in ("sessions", "users", "bookings", "class_sessions", "class_types", "gyms"):
        op.drop_table(table)
