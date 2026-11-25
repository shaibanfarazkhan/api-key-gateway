"""Shared FastAPI dependencies."""

from collections.abc import Generator
from dataclasses import dataclass
from hmac import compare_digest

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import APIKey, Organization
from app.services.authentication import APIKeyAuthenticationService

bearer_scheme = HTTPBearer(auto_error=False)
admin_bearer_scheme = HTTPBearer(auto_error=False)


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
    credentials: HTTPAuthorizationCredentials | None = Depends(  # noqa: B008
        bearer_scheme
    ),
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


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(  # noqa: B008
        admin_bearer_scheme
    ),
) -> None:
    """Allow access only to callers presenting the configured admin bearer key."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrative bearer key required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    configured_key = get_settings().admin_api_key
    if configured_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Administrative authentication is not configured",
        )
    if not compare_digest(credentials.credentials, configured_key.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative access forbidden",
        )
