"""Business logic for administrative resources."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import APIKey, Organization, Plan
from app.repositories.audit_logs import AuditLogRepository
from app.services.audit_logs import AuditLogService


class OrganizationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuditLogService(AuditLogRepository(db))

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
        previous_plan_ids = [
            str(assigned_plan.id) for assigned_plan in organization.plans
        ]
        organization.plans = [plan]
        self.audit.record(
            event_type="organization.plan_assigned",
            organization_id=organization.id,
            resource_type="organization",
            resource_id=organization.id,
            details={
                "previous_plan_ids": previous_plan_ids,
                "plan_id": str(plan.id),
            },
        )
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
        self.audit = AuditLogService(AuditLogRepository(db))

    def create(
        self,
        organization_id: UUID,
        *,
        expires_at: datetime | None = None,
        rotated_from_id: UUID | None = None,
    ) -> tuple[APIKey, str]:
        if self.db.get(Organization, organization_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        key, plaintext = self._build_key(
            organization_id,
            expires_at=expires_at,
            rotated_from_id=rotated_from_id,
        )
        self.db.add(key)
        self.db.flush()
        self.audit.record(
            event_type="api_key.created",
            organization_id=key.organization_id,
            resource_type="api_key",
            resource_id=key.id,
            details={"prefix": key.prefix},
        )
        self.db.commit()
        self.db.refresh(key)
        return key, plaintext

    def rotate(self, key_id: UUID) -> tuple[APIKey, str]:
        previous = self.db.scalar(
            select(APIKey).where(APIKey.id == key_id).with_for_update()
        )
        if previous is None:
            raise HTTPException(status_code=404, detail="API key not found")
        if previous.rotation_expires_at is not None:
            raise HTTPException(
                status_code=409, detail="API key has already been rotated"
            )

        replacement, plaintext = self._build_key(
            previous.organization_id,
            expires_at=previous.expires_at,
            rotated_from_id=previous.id,
        )
        previous.rotation_expires_at = datetime.now(UTC) + timedelta(
            seconds=get_settings().api_key_rotation_grace_seconds
        )
        self.db.add(replacement)
        self.db.flush()
        self.audit.record(
            event_type="api_key.rotated",
            organization_id=replacement.organization_id,
            resource_type="api_key",
            resource_id=replacement.id,
            details={
                "previous_key_id": str(previous.id),
                "replacement_key_id": str(replacement.id),
                "overlap_expires_at": previous.rotation_expires_at.isoformat(),
            },
        )
        self.db.commit()
        self.db.refresh(replacement)
        return replacement, plaintext

    def _build_key(
        self,
        organization_id: UUID,
        *,
        expires_at: datetime | None,
        rotated_from_id: UUID | None = None,
    ) -> tuple[APIKey, str]:
        plaintext = f"{self.KEY_PREFIX}{secrets.token_urlsafe(32)}"
        key = APIKey(
            organization_id=organization_id,
            key_hash=hashlib.sha256(plaintext.encode("utf-8")).hexdigest(),
            prefix=plaintext[: self.PREFIX_LENGTH],
            status="active",
            expires_at=expires_at,
            rotated_from_id=rotated_from_id,
        )
        return key, plaintext

    def revoke(self, key_id: UUID) -> APIKey:
        key = self.db.get(APIKey, key_id)
        if key is None:
            raise HTTPException(status_code=404, detail="API key not found")
        if key.status != "revoked":
            key.status = "revoked"
            key.revoked_at = datetime.now(UTC)
            self.audit.record(
                event_type="api_key.revoked",
                organization_id=key.organization_id,
                resource_type="api_key",
                resource_id=key.id,
                details={"revoked_at": key.revoked_at.isoformat()},
            )
            self.db.commit()
            self.db.refresh(key)
        return key
