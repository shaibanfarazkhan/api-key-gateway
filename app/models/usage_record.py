"""Monthly per-key usage record model."""

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.api_key import APIKey
    from app.models.organization import Organization


class UsageRecord(Base):
    """Monthly request count associated with an organization and API key."""

    __tablename__ = "usage_records"
    __table_args__ = (
        CheckConstraint(
            "request_count >= 0", name="ck_usage_records_count_nonnegative"
        ),
        UniqueConstraint(
            "organization_id",
            "api_key_id",
            "month",
            name="uq_usage_records_org_key_month",
        ),
        Index("ix_usage_records_organization_id", "organization_id"),
        Index("ix_usage_records_api_key_id", "api_key_id"),
        Index("ix_usage_records_month", "month"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    api_key_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("api_keys.id", ondelete="CASCADE"),
        nullable=False,
    )
    month: Mapped[date] = mapped_column(Date, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    organization: Mapped["Organization"] = relationship(back_populates="usage_records")
    api_key: Mapped["APIKey"] = relationship(back_populates="usage_records")
