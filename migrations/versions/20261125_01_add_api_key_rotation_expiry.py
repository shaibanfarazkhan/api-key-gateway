"""Add expiration deadline for rotated API keys.

Revision ID: 20261125_01
Revises: 20261117_01
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261125_01"
down_revision: str | None = "20261117_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the optional key rotation expiry deadline."""
    op.add_column(
        "api_keys",
        sa.Column("rotation_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove the key rotation expiry deadline."""
    op.drop_column("api_keys", "rotation_expires_at")
