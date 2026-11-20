"""Integration tests for the protected customer quote endpoint."""

import hashlib
import os
from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# The application engine is constructed during import; use an isolated SQLite DB.
os.environ["DATABASE_URL"] = "sqlite://"

from app.core.database import Base  # noqa: E402
from app.core.dependencies import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import APIKey, Organization, Plan, UsageRecord  # noqa: E402
from app.services.rate_limiter import RateLimitService  # noqa: E402

PLAINTEXT_KEY = "ak_quote-endpoint-test-key"


class AllowRedis:
    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[int]:
        return [1, 0]


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(engine, expire_on_commit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with test_session() as session:
            yield session

    monkeypatch.setattr("app.services.rate_limiter.redis_client", AllowRedis())
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, test_session
    app.dependency_overrides.clear()
    engine.dispose()


def create_customer(session_factory: sessionmaker[Session], *, quota: int) -> APIKey:
    with session_factory() as session:
        organization = Organization(name="Quote Customer", slug="quote-customer")
        plan = Plan(
            name="Quote Test Plan",
            requests_per_minute=10,
            monthly_quota=quota,
            active=True,
        )
        organization.plans = [plan]
        session.add(organization)
        session.flush()
        api_key = APIKey(
            organization_id=organization.id,
            key_hash=hashlib.sha256(PLAINTEXT_KEY.encode("utf-8")).hexdigest(),
            prefix=PLAINTEXT_KEY[:12],
            status="active",
        )
        session.add(api_key)
        session.commit()
        session.refresh(api_key)
        return api_key


def test_quote_returns_dummy_quote_and_reserves_monthly_quota(client) -> None:
    test_client, session_factory = client
    api_key = create_customer(session_factory, quota=1)
    headers = {"Authorization": f"Bearer {PLAINTEXT_KEY}"}

    response = test_client.get("/v1/quote", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "DEMO",
        "price": 100.0,
        "currency": "USD",
        "source": "dummy",
    }
    with session_factory() as session:
        record = session.scalar(
            select(UsageRecord).where(UsageRecord.api_key_id == api_key.id)
        )
    assert record is not None
    assert record.request_count == 1


def test_quote_reuses_authentication_rejection(client) -> None:
    test_client, session_factory = client
    create_customer(session_factory, quota=1)

    response = test_client.get("/v1/quote")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_quote_returns_existing_quota_exhaustion_error(client) -> None:
    test_client, session_factory = client
    create_customer(session_factory, quota=0)

    response = test_client.get(
        "/v1/quote", headers={"Authorization": f"Bearer {PLAINTEXT_KEY}"}
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "Monthly request quota exhausted"


def test_quote_returns_rate_limit_error_and_retry_after(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_client, session_factory = client
    create_customer(session_factory, quota=10)

    def reject_request(self: RateLimitService, organization_id: UUID) -> None:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": "17"},
        )

    monkeypatch.setattr(RateLimitService, "enforce", reject_request)
    response = test_client.get(
        "/v1/quote", headers={"Authorization": f"Bearer {PLAINTEXT_KEY}"}
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    assert response.json()["detail"] == "Rate limit exceeded"
