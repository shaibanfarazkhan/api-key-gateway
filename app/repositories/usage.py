"""Persistence operations for monthly usage accounting."""

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Organization, UsageRecord


class UsageRepository:
    """Reserve monthly organization quota using persisted usage records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def reserve_monthly_request(
        self,
        *,
        organization_id: UUID,
        api_key_id: UUID,
        month: date,
        monthly_quota: int,
    ) -> UsageRecord | None:
        """Increment this key's monthly usage if organization quota remains.

        The organization row lock serializes reservations for all keys belonging
        to the same organization on databases that support row-level locking.
        """
        locked_organization_id = self.db.scalar(
            select(Organization.id)
            .where(Organization.id == organization_id)
            .with_for_update()
        )
        if locked_organization_id is None:
            self.db.rollback()
            return None

        total_used = self.db.scalar(
            select(func.coalesce(func.sum(UsageRecord.request_count), 0)).where(
                UsageRecord.organization_id == locked_organization_id,
                UsageRecord.month == month,
            )
        )
        if (total_used or 0) >= monthly_quota:
            self.db.rollback()
            return None

        usage_record = self.db.scalar(
            select(UsageRecord).where(
                UsageRecord.organization_id == locked_organization_id,
                UsageRecord.api_key_id == api_key_id,
                UsageRecord.month == month,
            )
        )
        if usage_record is None:
            usage_record = UsageRecord(
                organization_id=locked_organization_id,
                api_key_id=api_key_id,
                month=month,
                request_count=1,
            )
            self.db.add(usage_record)
        else:
            usage_record.request_count += 1

        self.db.commit()
        self.db.refresh(usage_record)
        return usage_record
