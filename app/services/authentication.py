"""API key authentication policy."""

import hashlib
from datetime import UTC, datetime
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import APIKey, Organization
from app.repositories.api_keys import APIKeyRepository


class APIKeyAuthenticationService:
    """Validate presented keys against persisted lifecycle and tenant state."""

    def __init__(self, db: Session) -> None:
        self.api_keys = APIKeyRepository(db)

    def authenticate(self, plaintext_key: str) -> tuple[Organization, APIKey]:
        key_hash = hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()
        api_key = self.api_keys.get_with_organization_by_hash(key_hash)
        if api_key is None or api_key.status != "active":
            self._raise_unauthorized()

        now = datetime.now(UTC)
        expires_at = api_key.expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                self._raise_unauthorized()

        rotation_expires_at = api_key.rotation_expires_at
        if rotation_expires_at is not None:
            if rotation_expires_at.tzinfo is None:
                rotation_expires_at = rotation_expires_at.replace(tzinfo=UTC)
            if rotation_expires_at <= now:
                self._raise_unauthorized()

        organization = api_key.organization
        if organization.status != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization is inactive",
            )

        return organization, api_key

    @staticmethod
    def _raise_unauthorized() -> NoReturn:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
