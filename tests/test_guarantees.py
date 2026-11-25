"""Integration tests for persistence, accounting, and retry guarantees."""

import hashlib
import os
import sqlite3
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Constructing the production engine happens during module import.
os.environ["DATABASE_URL"] = "sqlite://"

from app.core.database import Base  # noqa: E402
from app.core.dependencies import get_db  # noqa: E402
from app.models import APIKey, Organization, Plan, UsageRecord  # noqa: E402
from app.services.admin import APIKeyService  # noqa: E402
from app.services.rate_limiter import RateLimitService  # noqa: E402

PLAINTEXT_KEY = "ak_guarantee-test-key"


class AllowRedis:
    """Admit test requests without requiring an external Redis service."""

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[int]:
        return [1, 0]


def seed_customer(session_factory: sessionmaker[Session]) -> Organization:
    with session_factory() as session:
        organization = Organization(name="Guarantee Org", slug=f"guarantee-{uuid4()}")
        organization.plans = [
            Plan(
                name=f"Guarantee Plan {uuid4()}",
                requests_per_minute=60,
                monthly_quota=100,
                active=True,
            )
        ]
        session.add(organization)
        session.flush()
        session.add(
            APIKey(
                organization_id=organization.id,
                key_hash=hashlib.sha256(PLAINTEXT_KEY.encode()).hexdigest(),
                prefix=PLAINTEXT_KEY[:12],
                status="active",
            )
        )
        session.commit()
        session.refresh(organization)
        return organization


def create_test_app(session_factory: sessionmaker[Session]) -> FastAPI:
    """Build quote and usage routes against an isolated persistent database."""
    from app.api.quotes import router as quote_router
    from app.api.usage import router as usage_router

    test_app = FastAPI()
    test_app.include_router(quote_router)
    test_app.include_router(usage_router)

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db
    return test_app


def test_database_dump_does_not_contain_plaintext_api_key(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        organization = Organization(name="Dump Org", slug="dump-org")
        session.add(organization)
        session.commit()
        key, plaintext = APIKeyService(session).create(organization.id)

    with sqlite3.connect(database_path) as connection:
        database_dump = "\n".join(connection.iterdump())

    digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    assert plaintext not in database_dump
    assert digest in database_dump
    assert key.prefix in database_dump
    engine.dispose()


def test_retries_with_same_idempotency_key_count_once(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    organization = seed_customer(session_factory)
    monkeypatch.setattr("app.services.rate_limiter.redis_client", AllowRedis())
    test_app = create_test_app(session_factory)

    with TestClient(test_app) as client:
        headers = {
            "Authorization": f"Bearer {PLAINTEXT_KEY}",
            "Idempotency-Key": "quote-request-123",
        }
        first = client.get("/v1/quote", headers=headers)
        retry = client.get("/v1/quote", headers=headers)
        usage = client.get(
            "/usage", headers={"Authorization": f"Bearer {PLAINTEXT_KEY}"}
        )

    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert usage.json()["requests_used_this_month"] == 1
    with session_factory() as session:
        records = list(
            session.scalars(
                select(UsageRecord).where(
                    UsageRecord.organization_id == organization.id
                )
            )
        )
    assert sum(record.request_count for record in records) == 1
    engine.dispose()


def test_usage_counts_only_successfully_served_quote_requests(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    seed_customer(session_factory)
    monkeypatch.setattr("app.services.rate_limiter.redis_client", AllowRedis())
    calls = 0

    def reject_second_request(
        self: RateLimitService, organization_id, plan=None
    ) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

    monkeypatch.setattr(RateLimitService, "enforce", reject_second_request)
    test_app = create_test_app(session_factory)
    with TestClient(test_app) as client:
        headers = {"Authorization": f"Bearer {PLAINTEXT_KEY}"}
        successful = client.get("/v1/quote", headers=headers)
        rejected = client.get("/v1/quote", headers=headers)
        usage = client.get("/usage", headers=headers)

    assert successful.status_code == 200
    assert rejected.status_code == 429
    assert usage.json()["requests_used_this_month"] == 1
    engine.dispose()


def test_usage_persists_after_new_app_and_engine_start(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "restart.sqlite"
    first_engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(first_engine)
    first_factory = sessionmaker(first_engine, expire_on_commit=False)
    seed_customer(first_factory)
    monkeypatch.setattr("app.services.rate_limiter.redis_client", AllowRedis())

    with TestClient(create_test_app(first_factory)) as client:
        response = client.get(
            "/v1/quote", headers={"Authorization": f"Bearer {PLAINTEXT_KEY}"}
        )
    assert response.status_code == 200
    first_engine.dispose()

    restarted_engine = create_engine(f"sqlite:///{database_path}")
    restarted_factory = sessionmaker(restarted_engine, expire_on_commit=False)
    with TestClient(create_test_app(restarted_factory)) as restarted_client:
        usage = restarted_client.get(
            "/usage", headers={"Authorization": f"Bearer {PLAINTEXT_KEY}"}
        )
    assert usage.status_code == 200
    assert usage.json()["requests_used_this_month"] == 1
    restarted_engine.dispose()
