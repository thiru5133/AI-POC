"""domains master data, a domain per business, shared per-domain assistants, and email OTP verification

Revision ID: 0009
"""

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    from app.domain.catalog import DOMAINS

    domains = op.create_table(
        "domains",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_domains_key", "domains", ["key"], unique=True)
    ids = {d.key: str(uuid.uuid4()) for d in DOMAINS}
    op.bulk_insert(
        domains,
        [{"id": ids[d.key], "key": d.key, "name": d.name, "description": d.description, "is_active": True} for d in DOMAINS],
    )

    with op.batch_alter_table("tenants") as batch:
        batch.add_column(sa.Column("domain_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("is_marketplace", sa.Boolean, nullable=False, server_default=sa.false()))
        batch.create_foreign_key("fk_tenants_domain_id", "domains", ["domain_id"], ["id"])
    # Everything that exists today is a hotel business (the demo hotel and test partners).
    op.execute(sa.text("UPDATE tenants SET domain_id = :d").bindparams(d=ids["hotel"]))
    op.execute(sa.text("UPDATE domain_profiles SET domain_type = 'hotel' WHERE domain_type = 'generic'"))

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email_verified_at", sa.DateTime, nullable=True))
    # Existing accounts are already in use: only accounts created from now on verify by OTP on first login.
    op.execute(sa.text("UPDATE users SET email_verified_at = :n").bindparams(n=datetime.now(timezone.utc).replace(tzinfo=None)))

    op.create_table(
        "email_otps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("consumed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_email_otps_user_id", "email_otps", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_email_otps_user_id", table_name="email_otps")
    op.drop_table("email_otps")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("email_verified_at")
    with op.batch_alter_table("tenants") as batch:
        batch.drop_constraint("fk_tenants_domain_id", type_="foreignkey")
        batch.drop_column("is_marketplace")
        batch.drop_column("domain_id")
    op.drop_index("ix_domains_key", table_name="domains")
    op.drop_table("domains")
