"""API key metadata model. Plaintext API keys are never persisted."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.usage_record import UsageRecord


class APIKey(Base):
    """An organization's hashed API key and lifecycle metadata."""

    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_organization_id", "organization_id"),
        Index("ix_api_keys_prefix", "prefix"),
        UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    rotated_from_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped["Organization"] = relationship(back_populates="api_keys")
    rotated_from: Mapped["APIKey | None"] = relationship(
        back_populates="rotated_to",
        remote_side="APIKey.id",
        foreign_keys=[rotated_from_id],
    )
    rotated_to: Mapped[list["APIKey"]] = relationship(
        back_populates="rotated_from",
        foreign_keys=[rotated_from_id],
    )
    usage_records: Mapped[list["UsageRecord"]] = relationship(
        back_populates="api_key",
        passive_deletes=True,
    )
