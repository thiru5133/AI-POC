"""MCP servers: free-form headers (secret or plain), transport and timeout

Replaces the single credential (auth_type + auth_token_enc) with a list of custom headers.

Revision ID: 0007
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    from app.core.config import get_settings
    from app.mcp.security import decrypt_secret, encrypt_secret

    op.add_column("mcp_servers", sa.Column("headers", sa.JSON, nullable=True))
    op.add_column("mcp_servers", sa.Column("transport", sa.String(20), nullable=False, server_default="streamable_http"))
    op.add_column("mcp_servers", sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default="15"))

    # Carry over saved credentials: API keys become an X-API-Key header, bearer tokens an Authorization header.
    settings = get_settings()
    conn = op.get_bind()
    for row_id, auth_type, token_enc in conn.execute(sa.text("SELECT id, auth_type, auth_token_enc FROM mcp_servers")).fetchall():
        headers = []
        if token_enc:
            token = decrypt_secret(settings, token_enc)
            name, value = ("X-API-Key", token) if auth_type == "api_key" else ("Authorization", f"Bearer {token}")
            headers.append({"name": name, "value": encrypt_secret(settings, value), "secret": True})
        conn.execute(sa.text("UPDATE mcp_servers SET headers = :h WHERE id = :i"), {"h": json.dumps(headers), "i": row_id})

    op.drop_column("mcp_servers", "auth_token_enc")
    op.drop_column("mcp_servers", "auth_type", mssql_drop_default=True)


def downgrade() -> None:
    op.add_column("mcp_servers", sa.Column("auth_type", sa.String(20), nullable=False, server_default="bearer"))
    op.add_column("mcp_servers", sa.Column("auth_token_enc", sa.Text, nullable=True))  # credentials are not restored
    op.drop_column("mcp_servers", "timeout_seconds", mssql_drop_default=True)
    op.drop_column("mcp_servers", "transport", mssql_drop_default=True)
    op.drop_column("mcp_servers", "headers")
