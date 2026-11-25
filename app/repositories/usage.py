"""Persistence operations for monthly usage accounting."""

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DailyUsageRecord, Organization, UsageRecord


class UsageRepository:
    """Reserve monthly organization quota using persisted usage records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_monthly_request_count(self, *, organization_id: UUID, month: date) -> int:
        """Return persisted request usage for one organization and month."""
        count = self.db.scalar(
            select(func.coalesce(func.sum(UsageRecord.request_count), 0)).where(
                UsageRecord.organization_id == organization_id,
                UsageRecord.month == month,
            )
        )
        return int(count or 0)

    def get_daily_request_counts(
        self, *, organization_id: UUID, start_day: date, end_day: date
    ) -> list[tuple[date, int]]:
        """Return tracked organization usage grouped by UTC day."""
        statement = (
            select(
                DailyUsageRecord.day,
                func.sum(DailyUsageRecord.request_count),
            )
            .where(
                DailyUsageRecord.organization_id == organization_id,
                DailyUsageRecord.day >= start_day,
                DailyUsageRecord.day <= end_day,
            )
            .group_by(DailyUsageRecord.day)
            .order_by(DailyUsageRecord.day)
        )
        return [(day, int(count)) for day, count in self.db.execute(statement)]

    def reserve_monthly_request(
        self,
        *,
        organization_id: UUID,
        api_key_id: UUID,
        month: date,
        day: date,
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

        daily_record = self.db.scalar(
            select(DailyUsageRecord).where(
                DailyUsageRecord.organization_id == locked_organization_id,
                DailyUsageRecord.api_key_id == api_key_id,
                DailyUsageRecord.day == day,
            )
        )
        if daily_record is None:
            daily_record = DailyUsageRecord(
                organization_id=locked_organization_id,
                api_key_id=api_key_id,
                day=day,
                request_count=1,
            )
            self.db.add(daily_record)
        else:
            daily_record.request_count += 1

        self.db.commit()
        self.db.refresh(usage_record)
        return usage_record
