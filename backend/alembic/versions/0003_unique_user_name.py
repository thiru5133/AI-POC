"""users can log in by name, so names must be unique

Revision ID: 0003
"""

from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.create_index("ix_users_name", "users", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_name", table_name="users")
