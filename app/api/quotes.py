"""Customer quote API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    get_db,
)
from app.schemas.quotes import QuoteResponse
from app.services.quota import QuotaService

router = APIRouter(prefix="/v1", tags=["quotes"])


@router.get("/quote", response_model=QuoteResponse)
def get_quote(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    db: Annotated[Session, Depends(get_db)],
) -> QuoteResponse:
    """Return a placeholder quote after authentication and quota reservation."""
    QuotaService(db).reserve_request(
        organization_id=principal.organization.id,
        api_key_id=principal.api_key.id,
    )
    return QuoteResponse(
        symbol="DEMO",
        price=100.0,
        currency="USD",
        source="dummy",
    )
