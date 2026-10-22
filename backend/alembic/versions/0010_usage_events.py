"""usage metering: one row per metered event (conversations, messages, voice seconds, tool calls, bookings, confirmations)

Revision ID: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_usage_events_tenant_id", "usage_events", ["tenant_id"])
    op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("usage_events")
