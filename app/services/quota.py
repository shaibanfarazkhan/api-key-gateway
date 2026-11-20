"""Monthly quota policy for authenticated organizations."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Organization, Plan, UsageRecord
from app.repositories.usage import UsageRepository


class QuotaService:
    """Apply an organization's active plan quota to an incoming request."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.usage = UsageRepository(db)

    def reserve_request(
        self, *, organization_id: UUID, api_key_id: UUID
    ) -> UsageRecord:
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

        active_plans = [plan for plan in organization.plans if plan.active]
        if not active_plans:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization has no active plan",
            )
        if len(active_plans) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Organization must have exactly one active plan",
            )

        plan: Plan = active_plans[0]
        current_month = datetime.now(UTC).date().replace(day=1)
        usage_record = self.usage.reserve_monthly_request(
            organization_id=organization_id,
            api_key_id=api_key_id,
            month=current_month,
            monthly_quota=plan.monthly_quota,
        )
        if usage_record is None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Monthly request quota exhausted",
            )
        return usage_record
