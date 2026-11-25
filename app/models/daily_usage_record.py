"""Daily usage aggregation model."""

from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.database import Base


class DailyUsageRecord(Base):
    """Request count by organization, API key, and UTC day."""

    __tablename__ = "daily_usage_records"
    __table_args__ = (
        CheckConstraint(
            "request_count >= 0", name="ck_daily_usage_records_count_nonnegative"
        ),
        UniqueConstraint(
            "organization_id",
            "api_key_id",
            "day",
            name="uq_daily_usage_records_org_key_day",
        ),
        Index("ix_daily_usage_records_org_day", "organization_id", "day"),
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
    day: Mapped[date] = mapped_column(Date, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
