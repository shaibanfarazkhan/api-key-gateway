"""Redis-backed sliding-window rate limiting."""

from uuid import UUID, uuid4

from fastapi import HTTPException, status
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.cache import redis_client
from app.core.config import get_settings
from app.models import Organization, Plan

WINDOW_MILLISECONDS = 60_000

SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local window_ms = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local member = ARGV[3]
local redis_time = redis.call('TIME')
local now_ms = (tonumber(redis_time[1]) * 1000)
    + math.floor(tonumber(redis_time[2]) / 1000)
local cutoff = now_ms - window_ms

redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)

if limit <= 0 then
    return {0, math.ceil(window_ms / 1000)}
end

local count = redis.call('ZCARD', key)
if count >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_ms = tonumber(oldest[2]) + window_ms - now_ms
    return {0, math.max(1, math.ceil(retry_ms / 1000))}
end

redis.call('ZADD', key, now_ms, member)
redis.call('PEXPIRE', key, window_ms)
return {1, 0}
"""


class RateLimitService:
    """Enforce plan-based per-organization sliding windows in Redis."""

    def __init__(self, db: Session, redis: Redis | None = None) -> None:
        self.db = db
        self.redis = redis if redis is not None else redis_client
        self.environment = get_settings().app_env

    def enforce(self, organization_id: UUID) -> None:
        """Admit a request or raise the applicable policy/dependency error."""
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

        active_plans = [plan for plan in organization.plans if plan.active]
        if not active_plans:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization has no active plan",
            )
        if len(active_plans) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Organization must have exactly one active plan",
            )

        plan: Plan = active_plans[0]
        redis_key = (
            f"{self.environment}:api-gateway:rate-limit:organization:{organization_id}"
        )
        try:
            allowed, retry_after = self.redis.eval(
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
