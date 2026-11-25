"""Organization-scoped, read-only usage reporting."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Organization, Plan
from app.repositories.usage import UsageRepository
from app.schemas.usage import ActivePlan, DailyUsage, UsageOrganization, UsageSummary
from app.services.plans import get_active_plan


class UsageService:
    """Build a current-month usage summary for an organization."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.usage = UsageRepository(db)

    def get_monthly_summary(
        self, organization_id: UUID, *, include_daily: bool = False
    ) -> UsageSummary:
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
        today = datetime.now(UTC).date()
        current_month = today.replace(day=1)
        requests_used = self.usage.get_monthly_request_count(
            organization_id=organization.id,
            month=current_month,
        )
        daily_breakdown = None
        if include_daily:
            daily_breakdown = [
                DailyUsage(day=day, request_count=count)
                for day, count in self.usage.get_daily_request_counts(
                    organization_id=organization.id,
                    start_day=current_month,
                    end_day=today,
                )
            ]
        percentage_used = (
            requests_used / plan.monthly_quota * 100
            if plan.monthly_quota
            else (100.0 if requests_used else 0.0)
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
            percentage_used=percentage_used,
            requests_per_minute=plan.requests_per_minute,
            current_month=current_month,
            daily_breakdown=daily_breakdown,
        )
