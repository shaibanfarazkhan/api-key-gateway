"""Persistence operations for administrative audit events."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import AuditLog


class AuditLogRepository:
    """Stage audit events in the caller's transaction."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        *,
        event_type: str,
        actor: str,
        organization_id: UUID | None,
        resource_type: str,
        resource_id: UUID,
        details: dict[str, Any],
    ) -> AuditLog:
        audit_log = AuditLog(
            event_type=event_type,
            actor=actor,
            organization_id=organization_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        self.db.add(audit_log)
        return audit_log
