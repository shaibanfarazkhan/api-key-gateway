"""Business logic for administrative resources."""

import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import APIKey, Organization, Plan


class OrganizationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, *, name: str, slug: str) -> Organization:
        if self.db.scalar(select(Organization.id).where(Organization.slug == slug)):
            raise HTTPException(
                status_code=409, detail="Organization slug already exists"
            )
        organization = Organization(name=name.strip(), slug=slug)
        self.db.add(organization)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=409, detail="Organization slug already exists"
            ) from exc
        self.db.refresh(organization)
        return organization

    def list(self) -> list[Organization]:
        return list(
            self.db.scalars(select(Organization).order_by(Organization.created_at))
        )

    def get(self, organization_id: UUID) -> Organization:
        organization = self.db.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        return organization

    def assign_plan(self, organization_id: UUID, plan_id: UUID) -> Organization:
        organization = self.get(organization_id)
        plan = self.db.get(Plan, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        organization.plans = [plan]
        self.db.commit()
        self.db.refresh(organization)
        return organization


class PlanService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self, *, name: str, requests_per_minute: int, monthly_quota: int, active: bool
    ) -> Plan:
        plan = Plan(
            name=name.strip(),
            requests_per_minute=requests_per_minute,
            monthly_quota=monthly_quota,
            active=active,
        )
        self.db.add(plan)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=409, detail="Plan name already exists"
            ) from exc
        self.db.refresh(plan)
        return plan


class APIKeyService:
    KEY_PREFIX = "ak_"
    PREFIX_LENGTH = 12

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        organization_id: UUID,
        *,
        expires_at: datetime | None = None,
        rotated_from_id: UUID | None = None,
    ) -> tuple[APIKey, str]:
        if self.db.get(Organization, organization_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        plaintext = f"{self.KEY_PREFIX}{secrets.token_urlsafe(32)}"
        key = APIKey(
            organization_id=organization_id,
            key_hash=hashlib.sha256(plaintext.encode("utf-8")).hexdigest(),
            prefix=plaintext[: self.PREFIX_LENGTH],
            status="active",
            expires_at=expires_at,
            rotated_from_id=rotated_from_id,
        )
        self.db.add(key)
        self.db.commit()
        self.db.refresh(key)
        return key, plaintext

    def rotate(self, key_id: UUID) -> tuple[APIKey, str]:
        previous = self.db.get(APIKey, key_id)
        if previous is None:
            raise HTTPException(status_code=404, detail="API key not found")
        # Keep the previous key active; the replacement records its lineage.
        return self.create(
            previous.organization_id,
            expires_at=previous.expires_at,
            rotated_from_id=previous.id,
        )

    def revoke(self, key_id: UUID) -> APIKey:
        key = self.db.get(APIKey, key_id)
        if key is None:
            raise HTTPException(status_code=404, detail="API key not found")
        if key.status != "revoked":
            key.status = "revoked"
            key.revoked_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(key)
        return key
