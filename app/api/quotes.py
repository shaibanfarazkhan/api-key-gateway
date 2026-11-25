"""Customer quote API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.dependencies import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    get_db,
)
from app.schemas.quotes import QuoteResponse
from app.services.plans import get_active_plan
from app.services.quota import QuotaService
from app.services.rate_limiter import RateLimitService

router = APIRouter(prefix="/v1", tags=["quotes"])


@router.get("/quote", response_model=QuoteResponse)
def get_quote(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=255)] = None,
) -> QuoteResponse:
    """Return a placeholder quote after auth, rate-limit, and quota checks."""
    plan = get_active_plan(principal.organization)
    quote = QuoteResponse(
        symbol="DEMO",
        price=100.0,
        currency="USD",
        source="dummy",
    )
    quota = QuotaService(db)
    if idempotency_key is not None and quota.is_idempotent_retry(
        api_key_id=principal.api_key.id,
        idempotency_key=idempotency_key,
    ):
        return quote
    RateLimitService(db).enforce(principal.organization.id, plan)
    quota.reserve_request(
        organization_id=principal.organization.id,
        api_key_id=principal.api_key.id,
        monthly_quota=plan.monthly_quota,
        idempotency_key=idempotency_key,
    )
    return quote
