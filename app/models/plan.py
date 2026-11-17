"""Plan model."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.core.database import Base
from app.models.organization import organization_plans


class Plan(Base):
    """A set of request entitlements assignable to organizations."""

    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("requests_per_minute >= 0", name="ck_plans_rpm_nonnegative"),
        CheckConstraint("monthly_quota >= 0", name="ck_plans_quota_nonnegative"),
        UniqueConstraint("name", name="uq_plans_name"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    requests_per_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    organizations: Mapped[list["Organization"]] = relationship(
        secondary=organization_plans,
        back_populates="plans",
    )
