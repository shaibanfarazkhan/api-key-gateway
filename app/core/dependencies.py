"""Shared FastAPI dependencies."""

from collections.abc import Generator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import APIKey, Organization
from app.services.authentication import APIKeyAuthenticationService

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """The organization and API key associated with a valid bearer token."""

    organization: Organization
    api_key: APIKey


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and always close it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_authenticated_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AuthenticatedPrincipal:
    """Authenticate a bearer API key and return its organization and key."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    organization, api_key = APIKeyAuthenticationService(db).authenticate(
        credentials.credentials
    )
    return AuthenticatedPrincipal(organization=organization, api_key=api_key)
