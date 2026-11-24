"""Persistence queries for API key authentication."""

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import APIKey, Organization


class APIKeyRepository:
    """Read API key metadata needed to authenticate a credential."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_with_organization_by_hash(self, key_hash: str) -> APIKey | None:
        statement = (
            select(APIKey)
            .options(
                joinedload(APIKey.organization).selectinload(Organization.plans)
            )
            .where(APIKey.key_hash == key_hash)
        )
        return self.db.scalar(statement)
