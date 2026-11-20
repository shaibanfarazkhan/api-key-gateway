"""Integration tests for authenticated monthly usage reporting."""

import hashlib
import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
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

PLAINTEXT_KEY = "ak_usage-endpoint-test-key"


@pytest.fixture
def client() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
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

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, test_session
    app.dependency_overrides.clear()
    engine.dispose()


def seed_customer(
    session_factory: sessionmaker[Session],
    *,
    slug: str,
    usage: int,
    plaintext_key: str = PLAINTEXT_KEY,
) -> tuple[Organization, Plan, APIKey]:
    with session_factory() as session:
        organization = Organization(name="Usage Customer", slug=slug)
        plan = Plan(
            name=f"Usage Plan {uuid4()}",
            requests_per_minute=25,
            monthly_quota=100,
            active=True,
        )
        organization.plans = [plan]
        session.add(organization)
        session.flush()
        api_key = APIKey(
            organization_id=organization.id,
            key_hash=hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest(),
            prefix=plaintext_key[:12],
            status="active",
        )
        another_key = APIKey(
            organization_id=organization.id,
            key_hash=hashlib.sha256(f"other-{slug}".encode()).hexdigest(),
            prefix="ak_other",
            status="active",
        )
        session.add_all([api_key, another_key])
        session.flush()
        month = datetime.now(UTC).date().replace(day=1)
        if usage:
            session.add_all(
                [
                    UsageRecord(
                        organization_id=organization.id,
                        api_key_id=api_key.id,
                        month=month,
                        request_count=usage // 2,
                    ),
                    UsageRecord(
                        organization_id=organization.id,
                        api_key_id=another_key.id,
                        month=month,
                        request_count=usage - usage // 2,
                    ),
                    UsageRecord(
                        organization_id=organization.id,
                        api_key_id=api_key.id,
                        month=(month - timedelta(days=1)).replace(day=1),
                        request_count=7,
                    ),
                ]
            )
        session.commit()
        session.refresh(organization)
        session.refresh(plan)
        session.refresh(api_key)
        return organization, plan, api_key


def test_usage_returns_org_scoped_monthly_summary_without_writing(client) -> None:
    test_client, session_factory = client
    organization, plan, api_key = seed_customer(
        session_factory, slug="usage-customer", usage=23
    )

    response = test_client.get(
        "/usage", headers={"Authorization": f"Bearer {PLAINTEXT_KEY}"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "organization": {
            "id": str(organization.id),
            "name": "Usage Customer",
            "slug": "usage-customer",
        },
        "active_plan": {"id": str(plan.id), "name": plan.name},
        "requests_used_this_month": 23,
        "monthly_quota": 100,
        "remaining_quota": 77,
        "requests_per_minute": 25,
        "current_month": datetime.now(UTC).date().replace(day=1).isoformat(),
    }
    with session_factory() as session:
        records = list(
            session.scalars(
                select(UsageRecord).where(
                    UsageRecord.organization_id == organization.id
                )
            )
        )
    assert sum(record.request_count for record in records) == 30
    assert api_key.organization_id == organization.id


def test_usage_is_scoped_to_the_authenticated_organization(client) -> None:
    test_client, session_factory = client
    first_org, _, _ = seed_customer(session_factory, slug="first-customer", usage=12)
    second_org, _, _ = seed_customer(
        session_factory,
        slug="second-customer",
        usage=51,
        plaintext_key="ak_second-usage-key",
    )

    response = test_client.get(
        "/usage", headers={"Authorization": f"Bearer {PLAINTEXT_KEY}"}
    )

    assert response.status_code == 200
    assert response.json()["organization"]["id"] == str(first_org.id)
    assert response.json()["requests_used_this_month"] == 12
    assert response.json()["organization"]["id"] != str(second_org.id)


def test_usage_requires_authentication(client) -> None:
    test_client, _ = client

    response = test_client.get("/usage")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
