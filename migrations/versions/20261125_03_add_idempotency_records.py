"""Persist quote request idempotency tokens.

Revision ID: 20261125_03
Revises: 20261125_02
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261125_03"
down_revision: str | None = "20261125_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create storage for deduplicating retried quote requests."""
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("api_key_id", sa.Uuid(), nullable=False),
        sa.Column("usage_record_id", sa.Uuid(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["usage_record_id"], ["usage_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "api_key_id", "key_hash", name="uq_idempotency_records_key_hash"
        ),
    )
    op.create_index(
        "ix_idempotency_records_org_created",
        "idempotency_records",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    """Drop idempotency request records."""
    op.drop_index(
        "ix_idempotency_records_org_created", table_name="idempotency_records"
    )
    op.drop_table("idempotency_records")
