"""Response schemas for organization usage reporting."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class UsageOrganization(BaseModel):
    id: UUID
    name: str
    slug: str


class ActivePlan(BaseModel):
    id: UUID
    name: str


class DailyUsage(BaseModel):
    day: date
    request_count: int


class UsageSummary(BaseModel):
    organization: UsageOrganization
    active_plan: ActivePlan
    requests_used_this_month: int
    monthly_quota: int
    remaining_quota: int
    percentage_used: float
    requests_per_minute: int
    current_month: date
    daily_breakdown: list[DailyUsage] | None = Field(
        default=None,
        description=(
            "Tracked daily counts from the start of daily usage collection; "
            "older monthly aggregates cannot be split by day."
        ),
    )
