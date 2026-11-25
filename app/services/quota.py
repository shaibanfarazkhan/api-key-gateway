"""Monthly quota policy for authenticated organizations."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Organization, Plan, UsageRecord
from app.repositories.usage import UsageRepository
from app.services.plans import get_active_plan


class QuotaService:
    """Apply an organization's active plan quota to an incoming request."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.usage = UsageRepository(db)

    def reserve_request(
        self,
        *,
        organization_id: UUID,
        api_key_id: UUID,
        monthly_quota: int | None = None,
    ) -> UsageRecord:
        if monthly_quota is None:
            organization = self.db.scalar(
                select(Organization)
                .options(selectinload(Organization.plans))
                .where(Organization.id == organization_id)
            )
            if organization is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Organization not found",
                )
            plan: Plan = get_active_plan(organization)
            monthly_quota = plan.monthly_quota

        current_day = datetime.now(UTC).date()
        current_month = current_day.replace(day=1)
        usage_record = self.usage.reserve_monthly_request(
            organization_id=organization_id,
            api_key_id=api_key_id,
            month=current_month,
            day=current_day,
            monthly_quota=monthly_quota,
        )
        if usage_record is None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Monthly request quota exhausted",
            )
        return usage_record
