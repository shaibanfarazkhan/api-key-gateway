"""Redis client configuration."""

from __future__ import annotations

from typing import Any, Protocol, cast

from redis import Redis

from app.core.config import get_settings


class RedisClient(Protocol):
    """Redis commands required by application services."""

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...


redis_client: RedisClient = cast(
    RedisClient,
    Redis.from_url(get_settings().redis_url, decode_responses=True),
)
