"""Response schemas for organization usage reporting."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel


class UsageOrganization(BaseModel):
    id: UUID
    name: str
    slug: str


class ActivePlan(BaseModel):
    id: UUID
    name: str


class UsageSummary(BaseModel):
    organization: UsageOrganization
    active_plan: ActivePlan
    requests_used_this_month: int
    monthly_quota: int
    remaining_quota: int
    requests_per_minute: int
    current_month: date
