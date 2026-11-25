"""Redis-backed sliding-window rate limiting."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.cache import RedisClient, redis_client
from app.core.config import get_settings
from app.core.rate_limit_script import SLIDING_WINDOW_SCRIPT, WINDOW_MILLISECONDS
from app.models import Organization, Plan
from app.services.plans import get_active_plan


class RateLimitService:
    """Enforce plan-based per-organization sliding windows in Redis."""

    def __init__(self, db: Session, redis: RedisClient | None = None) -> None:
        self.db = db
        self.redis = redis if redis is not None else redis_client
        self.environment = get_settings().app_env
        register_script = getattr(self.redis, "register_script", None)
        self._script = (
            register_script(SLIDING_WINDOW_SCRIPT) if register_script else None
        )

    def enforce(self, organization_id: UUID, plan: Plan | None = None) -> None:
        """Admit a request or raise the applicable policy/dependency error."""
        if plan is None:
            organization = self.db.scalar(
                select(Organization)
                .options(selectinload(Organization.plans))
                .where(Organization.id == organization_id)
            )
            if organization is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Organization not found",
                )
            plan = get_active_plan(organization)

        redis_key = (
            f"{self.environment}:api-gateway:rate-limit:organization:{organization_id}"
        )
        try:
            if self._script is not None:
                allowed, retry_after = self._script(
                    keys=[redis_key],
                    args=[
                        WINDOW_MILLISECONDS,
                        plan.requests_per_minute,
                        str(uuid4()),
                    ],
                )
            else:
                allowed, retry_after = cast(Any, self.redis).eval(
                    SLIDING_WINDOW_SCRIPT,
                    1,
                    redis_key,
                    WINDOW_MILLISECONDS,
                    plan.requests_per_minute,
                    str(uuid4()),
                )
        except RedisError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiter unavailable",
            ) from exc

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
