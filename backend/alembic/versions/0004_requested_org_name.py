"""admin signup requests carry the organization they want created on approval

Revision ID: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.add_column("users", sa.Column("requested_org_name", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "requested_org_name")
