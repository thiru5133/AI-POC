"""phone numbers: which number a business answers calls on, and where its calls are transferred to a person

Revision ID: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.create_table(
        "phone_numbers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False, unique=True),
        sa.Column("number", sa.String(20), nullable=False),
        sa.Column("transfer_number", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_phone_numbers_number", "phone_numbers", ["number"], unique=True)


def downgrade() -> None:
    op.drop_table("phone_numbers")
