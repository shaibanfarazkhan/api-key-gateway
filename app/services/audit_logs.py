"""Application service for recording administrative audit events."""

from typing import Any
from uuid import UUID

from app.models import AuditLog
from app.repositories.audit_logs import AuditLogRepository


class AuditLogService:
    """Stage sanitized audit events in the current database transaction."""

    def __init__(self, repository: AuditLogRepository) -> None:
        self.repository = repository

    def record(
        self,
        *,
        event_type: str,
        organization_id: UUID | None,
        resource_type: str,
        resource_id: UUID,
        details: dict[str, Any],
    ) -> AuditLog:
        """Add an admin event; the business operation commits it atomically."""
        return self.repository.add(
            event_type=event_type,
            actor="admin",
            organization_id=organization_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
