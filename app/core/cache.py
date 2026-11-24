"""Redis client configuration."""

from __future__ import annotations

from typing import Any

from redis import Redis

from app.core.config import get_settings

redis_client: Redis[Any] = Redis.from_url(
    get_settings().redis_url, decode_responses=True
)
