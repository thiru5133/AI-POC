"""MCP servers: how the credential is sent (API key header or bearer token)

Revision ID: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    # Credentials saved before this migration were sent as Bearer tokens.
    op.add_column("mcp_servers", sa.Column("auth_type", sa.String(20), nullable=False, server_default="bearer"))


def downgrade() -> None:
    op.drop_column("mcp_servers", "auth_type")
