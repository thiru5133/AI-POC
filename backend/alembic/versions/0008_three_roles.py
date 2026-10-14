"""three roles: tenants can be disabled, conversations remember their customer, user names are no longer unique

Revision ID: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.add_column("tenants", sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()))
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_conversations_user_id", "users", ["user_id"], ["id"])
        batch.create_index("ix_conversations_user_id", ["user_id"])
    # Customers share common names, and everyone now logs in by email.
    op.drop_index("ix_users_name", table_name="users")
    op.create_index("ix_users_name", "users", ["name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_name", table_name="users")
    op.create_index("ix_users_name", "users", ["name"], unique=True)
    with op.batch_alter_table("conversations") as batch:
        batch.drop_index("ix_conversations_user_id")
        batch.drop_constraint("fk_conversations_user_id", type_="foreignkey")
        batch.drop_column("user_id")
    op.drop_column("tenants", "is_active")
