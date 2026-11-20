"""Organization-scoped, read-only usage reporting."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Organization, Plan
from app.repositories.usage import UsageRepository
from app.schemas.usage import ActivePlan, UsageOrganization, UsageSummary


class UsageService:
    """Build a current-month usage summary for an organization."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.usage = UsageRepository(db)

    def get_monthly_summary(self, organization_id: UUID) -> UsageSummary:
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
        requests_used = self.usage.get_monthly_request_count(
            organization_id=organization.id,
            month=current_month,
        )
        return UsageSummary(
            organization=UsageOrganization(
                id=organization.id,
                name=organization.name,
                slug=organization.slug,
            ),
            active_plan=ActivePlan(id=plan.id, name=plan.name),
            requests_used_this_month=requests_used,
            monthly_quota=plan.monthly_quota,
            remaining_quota=max(plan.monthly_quota - requests_used, 0),
            requests_per_minute=plan.requests_per_minute,
            current_month=current_month,
        )
