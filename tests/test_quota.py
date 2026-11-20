"""Tests for monthly organization quota reservation."""

import os
from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# The application engine is constructed during import; use an isolated SQLite DB.
os.environ["DATABASE_URL"] = "sqlite://"

from app.core.database import Base  # noqa: E402
from app.models import APIKey, Organization, Plan, UsageRecord  # noqa: E402
from app.services.quota import QuotaService  # noqa: E402


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def create_customer(
    session_factory: sessionmaker[Session], *, quota: int | None
) -> tuple[Organization, APIKey, Plan | None]:
    with session_factory() as session:
        organization = Organization(name="Example", slug="example")
        session.add(organization)
        session.flush()

        api_key = APIKey(
            organization_id=organization.id,
            key_hash="digest",
            prefix="ak_test",
            status="active",
        )
        session.add(api_key)

        plan = None
        if quota is not None:
            plan = Plan(
                name=f"Plan {uuid4()}",
                requests_per_minute=60,
                monthly_quota=quota,
                active=True,
            )
            organization.plans = [plan]

        session.commit()
        session.refresh(organization)
        session.refresh(api_key)
        if plan is not None:
            session.refresh(plan)
        return organization, api_key, plan


def reserve_request(
    session_factory: sessionmaker[Session],
    *,
    organization_id: UUID,
    api_key_id: UUID,
) -> UsageRecord:
    with session_factory() as session:
        return QuotaService(session).reserve_request(
            organization_id=organization_id,
            api_key_id=api_key_id,
        )


def test_request_is_reserved_and_usage_recorded(session_factory) -> None:
    organization, api_key, _ = create_customer(session_factory, quota=2)

    record = reserve_request(
        session_factory,
        organization_id=organization.id,
        api_key_id=api_key.id,
    )

    assert record.request_count == 1
    assert record.month == datetime.now(UTC).date().replace(day=1)


def test_quota_applies_across_all_organization_keys(session_factory) -> None:
    organization, api_key, _ = create_customer(session_factory, quota=1)
    another_key_id = uuid4()
    with session_factory() as session:
        another_key = APIKey(
            id=another_key_id,
            organization_id=organization.id,
            key_hash="other-digest",
            prefix="ak_other",
            status="active",
        )
        session.add(another_key)
        session.commit()

    reserve_request(
        session_factory,
        organization_id=organization.id,
        api_key_id=api_key.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        reserve_request(
            session_factory,
            organization_id=organization.id,
            api_key_id=another_key_id,
        )

    assert exc_info.value.status_code == 429
    with session_factory() as session:
        records = list(
            session.scalars(
                select(UsageRecord).where(
                    UsageRecord.organization_id == organization.id
                )
            )
        )
    assert len(records) == 1
    assert records[0].api_key_id == api_key.id


def test_existing_usage_increments_until_quota_is_reached(session_factory) -> None:
    organization, api_key, _ = create_customer(session_factory, quota=2)
    reserve_request(
        session_factory,
        organization_id=organization.id,
        api_key_id=api_key.id,
    )
    record = reserve_request(
        session_factory, organization_id=organization.id, api_key_id=api_key.id
    )

    assert record.request_count == 2
    with pytest.raises(HTTPException) as exc_info:
        reserve_request(
            session_factory,
            organization_id=organization.id,
            api_key_id=api_key.id,
        )
    assert exc_info.value.status_code == 429


def test_organization_without_plan_cannot_reserve(session_factory) -> None:
    organization, api_key, _ = create_customer(session_factory, quota=None)

    with pytest.raises(HTTPException) as exc_info:
        reserve_request(
            session_factory,
            organization_id=organization.id,
            api_key_id=api_key.id,
        )

    assert exc_info.value.status_code == 403


def test_inactive_plan_cannot_reserve(session_factory) -> None:
    organization, api_key, plan = create_customer(session_factory, quota=10)
    assert plan is not None
    with session_factory() as session:
        stored_plan = session.get(Plan, plan.id)
        assert stored_plan is not None
        stored_plan.active = False
        session.commit()

    with pytest.raises(HTTPException) as exc_info:
        reserve_request(
            session_factory,
            organization_id=organization.id,
            api_key_id=api_key.id,
        )

    assert exc_info.value.status_code == 403
