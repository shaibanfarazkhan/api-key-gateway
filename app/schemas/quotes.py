"""Response schemas for the customer quote API."""

from pydantic import BaseModel


class QuoteResponse(BaseModel):
    """Public quote response shape for the current placeholder provider."""

    symbol: str
    price: float
    currency: str
    source: str
