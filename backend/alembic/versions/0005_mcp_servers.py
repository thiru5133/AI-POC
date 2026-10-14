"""per-organization MCP server connections

Revision ID: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("auth_token_enc", sa.Text, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_mcp_servers_tenant_name"),
    )
    op.create_index("ix_mcp_servers_tenant_id", "mcp_servers", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_servers_tenant_id", table_name="mcp_servers")
    op.drop_table("mcp_servers")
