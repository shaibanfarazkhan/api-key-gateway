"""Tests for the Redis-backed organization rate limiter."""

import os
from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# The application engine is constructed during import; use an isolated SQLite DB.
os.environ["DATABASE_URL"] = "sqlite://"

from app.core.config import get_settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.core.dependencies import get_db  # noqa: E402
from app.models import Organization, Plan  # noqa: E402
from app.services.rate_limiter import (  # noqa: E402
    SLIDING_WINDOW_SCRIPT,
    WINDOW_MILLISECONDS,
    RateLimitService,
)


class FakeRedis:
    """Small shared sorted-set fake for exercising limiter service behavior."""

    def __init__(self) -> None:
        self.now_ms = 1_000_000
        self.windows: dict[str, list[tuple[int, str]]] = {}
        self.keys: list[str] = []

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[int]:
        assert script == SLIDING_WINDOW_SCRIPT
        assert numkeys == 1
        key = str(keys_and_args[0])
        window_ms = int(keys_and_args[1])
        limit = int(keys_and_args[2])
        member = str(keys_and_args[3])
        self.keys.append(key)

        events = [
            (score, value)
            for score, value in self.windows.get(key, [])
            if score > self.now_ms - window_ms
        ]
        self.windows[key] = events
        if limit <= 0:
            return [0, (window_ms + 999) // 1000]
        if len(events) >= limit:
            retry_ms = events[0][0] + window_ms - self.now_ms
            return [0, max(1, (retry_ms + 999) // 1000)]

        events.append((self.now_ms, member))
        return [1, 0]


class UnavailableRedis:
    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[int]:
        raise RedisConnectionError("Redis is unavailable")


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(engine, expire_on_commit=False)
    with test_session() as session:
        yield session
    engine.dispose()


def create_organization(session: Session, *, requests_per_minute: int) -> Organization:
    organization = Organization(name="Rate Limited", slug=f"org-{uuid4()}")
    organization.plans = [
        Plan(
            name=f"Rate Plan {uuid4()}",
            requests_per_minute=requests_per_minute,
            monthly_quota=100,
            active=True,
        )
    ]
    session.add(organization)
    session.commit()
    session.refresh(organization)
    return organization


def test_allows_requests_within_organization_limit(db_session: Session) -> None:
    organization = create_organization(db_session, requests_per_minute=2)
    redis = FakeRedis()
    limiter = RateLimitService(db_session, redis)

    limiter.enforce(organization.id)
    limiter.enforce(organization.id)

    assert len(redis.windows[next(iter(redis.windows))]) == 2


def test_rejects_excess_requests_with_retry_after(db_session: Session) -> None:
    organization = create_organization(db_session, requests_per_minute=1)
    redis = FakeRedis()
    limiter = RateLimitService(db_session, redis)
    limiter.enforce(organization.id)

    with pytest.raises(HTTPException) as exc_info:
        limiter.enforce(organization.id)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Rate limit exceeded"
    assert int(exc_info.value.headers["Retry-After"]) > 0


def test_sliding_window_admits_again_after_old_request_expires(
    db_session: Session,
) -> None:
    organization = create_organization(db_session, requests_per_minute=1)
    redis = FakeRedis()
    limiter = RateLimitService(db_session, redis)
    limiter.enforce(organization.id)

    redis.now_ms += WINDOW_MILLISECONDS
    limiter.enforce(organization.id)

    assert len(redis.windows[redis.keys[0]]) == 1


def test_limiter_state_is_shared_across_service_instances(db_session: Session) -> None:
    organization = create_organization(db_session, requests_per_minute=1)
    redis = FakeRedis()
    first_instance = RateLimitService(db_session, redis)
    second_instance = RateLimitService(db_session, redis)
    first_instance.enforce(organization.id)

    with pytest.raises(HTTPException) as exc_info:
        second_instance.enforce(organization.id)

    assert exc_info.value.status_code == 429


def test_limiter_is_shared_by_independent_redis_clients(db_session: Session) -> None:
    settings = get_settings()
    first_redis = Redis.from_url(settings.redis_url)
    second_redis = Redis.from_url(settings.redis_url)
    try:
        first_redis.ping()
    except RedisConnectionError:
        first_redis.close()
        second_redis.close()
        if os.getenv("CI"):
            raise
        pytest.skip("A live Redis service is required for this integration test")

    organization = create_organization(db_session, requests_per_minute=1)
    redis_key = (
        f"{settings.app_env}:api-gateway:rate-limit:organization:{organization.id}"
    )
    first_redis.delete(redis_key)
    second_session_factory = sessionmaker(bind=db_session.get_bind())

    def make_application(redis_client: Redis) -> FastAPI:
        application = FastAPI()

        def override_get_db() -> Generator[Session, None, None]:
            with second_session_factory() as session:
                yield session

        application.dependency_overrides[get_db] = override_get_db

        @application.get("/limited")
        def limited(db: Session = Depends(get_db)) -> dict[str, str]:  # noqa: B008
            RateLimitService(db, redis_client).enforce(organization.id)
            return {"result": "allowed"}

        return application

    try:
        with TestClient(make_application(first_redis)) as first_app_client:
            first_response = first_app_client.get("/limited")
        with TestClient(make_application(second_redis)) as second_app_client:
            second_response = second_app_client.get("/limited")
        assert first_response.status_code == 200
        assert second_response.status_code == 429
    finally:
        first_redis.delete(redis_key)
        first_redis.close()
        second_redis.close()


def test_rate_limits_are_isolated_per_organization(db_session: Session) -> None:
    first_organization = create_organization(db_session, requests_per_minute=1)
    second_organization = create_organization(db_session, requests_per_minute=1)
    redis = FakeRedis()
    limiter = RateLimitService(db_session, redis)

    limiter.enforce(first_organization.id)
    limiter.enforce(second_organization.id)

    assert redis.keys[0] != redis.keys[1]


def test_redis_failure_returns_service_unavailable(db_session: Session) -> None:
    organization = create_organization(db_session, requests_per_minute=1)
    limiter = RateLimitService(db_session, UnavailableRedis())  # type: ignore[arg-type]

    with pytest.raises(HTTPException) as exc_info:
        limiter.enforce(organization.id)

    assert exc_info.value.status_code == 503


def test_missing_organization_is_reported(db_session: Session) -> None:
    limiter = RateLimitService(db_session, FakeRedis())

    with pytest.raises(HTTPException) as exc_info:
        limiter.enforce(UUID(int=0))

    assert exc_info.value.status_code == 404
