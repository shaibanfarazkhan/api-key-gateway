"""Customer usage reporting routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    get_db,
)
from app.schemas.usage import UsageSummary
from app.services.usage import UsageService

router = APIRouter(tags=["usage"])


@router.get("/usage", response_model=UsageSummary, response_model_exclude_none=True)
def get_usage(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    db: Annotated[Session, Depends(get_db)],
    include_daily: bool = Query(default=False),
) -> UsageSummary:
    """Return monthly usage scoped to the authenticated organization."""
    return UsageService(db).get_monthly_summary(
        principal.organization.id, include_daily=include_daily
    )
