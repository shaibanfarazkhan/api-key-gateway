"""Shared active-plan validation for authenticated requests."""

from fastapi import HTTPException, status

from app.models import Organization, Plan


def get_active_plan(organization: Organization) -> Plan:
    """Return the organization's sole active plan or raise a policy error."""
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
    return active_plans[0]
