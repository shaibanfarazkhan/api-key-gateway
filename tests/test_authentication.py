"""Tests for the reusable API key authentication dependency."""

import hashlib
import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# The application engine is constructed during import; use an isolated SQLite DB.
os.environ["DATABASE_URL"] = "sqlite://"

from app.core.config import get_settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.core.dependencies import (  # noqa: E402
    AuthenticatedPrincipal,
    get_authenticated_principal,
    get_db,
)
from app.models import APIKey, Organization  # noqa: E402
from app.services.admin import APIKeyService  # noqa: E402


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

    app = FastAPI()

    @app.get("/protected")
    def protected(
        principal: AuthenticatedPrincipal = Depends(  # noqa: B008
            get_authenticated_principal
        ),
    ) -> dict[str, str]:
        return {
            "organization_id": str(principal.organization.id),
            "api_key_id": str(principal.api_key.id),
        }

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, test_session
    app.dependency_overrides.clear()
    engine.dispose()


def create_key(
    session_factory: sessionmaker[Session],
    *,
    organization_status: str = "active",
    key_status: str = "active",
    expires_at: datetime | None = None,
) -> tuple[str, Organization, APIKey]:
    plaintext = "ak_test-authentication-key"
    with session_factory() as session:
        organization = Organization(
            name="Example", slug="example", status=organization_status
        )
        session.add(organization)
        session.flush()
        api_key = APIKey(
            organization_id=organization.id,
            key_hash=hashlib.sha256(plaintext.encode("utf-8")).hexdigest(),
            prefix=plaintext[:12],
            status=key_status,
            expires_at=expires_at,
        )
        session.add(api_key)
        session.commit()
        session.refresh(organization)
        session.refresh(api_key)
        return plaintext, organization, api_key


def test_valid_key_returns_organization_and_api_key(client) -> None:
    test_client, session_factory = client
    plaintext, organization, api_key = create_key(session_factory)

    response = test_client.get(
        "/protected", headers={"Authorization": f"Bearer {plaintext}"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "organization_id": str(organization.id),
        "api_key_id": str(api_key.id),
    }


def test_rotated_keys_work_during_grace_and_old_key_expires_afterward(client) -> None:
    test_client, session_factory = client
    old_plaintext, organization, old_key = create_key(session_factory)
    settings = get_settings()
    old_grace = settings.api_key_rotation_grace_seconds
    settings.api_key_rotation_grace_seconds = 120
    try:
        with session_factory() as session:
            replacement, new_plaintext = APIKeyService(session).rotate(old_key.id)
            rotation_deadline = session.get(APIKey, old_key.id).rotation_expires_at

        assert rotation_deadline is not None
        if rotation_deadline.tzinfo is None:
            rotation_deadline = rotation_deadline.replace(tzinfo=UTC)
        remaining_seconds = (rotation_deadline - datetime.now(UTC)).total_seconds()
        assert 119 <= remaining_seconds <= 120

        for plaintext in (old_plaintext, new_plaintext):
            response = test_client.get(
                "/protected", headers={"Authorization": f"Bearer {plaintext}"}
            )
            assert response.status_code == 200
            assert response.json()["organization_id"] == str(organization.id)

        with session_factory() as session:
            expired_old_key = session.get(APIKey, old_key.id)
            assert expired_old_key is not None
            expired_old_key.rotation_expires_at = datetime.now(UTC) - timedelta(
                seconds=1
            )
            session.commit()

        old_response = test_client.get(
            "/protected", headers={"Authorization": f"Bearer {old_plaintext}"}
        )
        new_response = test_client.get(
            "/protected", headers={"Authorization": f"Bearer {new_plaintext}"}
        )
        assert old_response.status_code == 401
        assert new_response.status_code == 200
        assert replacement.rotated_from_id == old_key.id
    finally:
        settings.api_key_rotation_grace_seconds = old_grace


def test_invalid_key_is_rejected(client) -> None:
    test_client, session_factory = client
    create_key(session_factory)

    response = test_client.get(
        "/protected", headers={"Authorization": "Bearer ak_invalid"}
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_revoked_key_is_rejected(client) -> None:
    test_client, session_factory = client
    plaintext, _, _ = create_key(session_factory, key_status="revoked")

    response = test_client.get(
        "/protected", headers={"Authorization": f"Bearer {plaintext}"}
    )

    assert response.status_code == 401


def test_expired_key_is_rejected(client) -> None:
    test_client, session_factory = client
    plaintext, _, _ = create_key(
        session_factory,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    response = test_client.get(
        "/protected", headers={"Authorization": f"Bearer {plaintext}"}
    )

    assert response.status_code == 401


def test_inactive_organization_is_rejected(client) -> None:
    test_client, session_factory = client
    plaintext, _, _ = create_key(session_factory, organization_status="suspended")

    response = test_client.get(
        "/protected", headers={"Authorization": f"Bearer {plaintext}"}
    )

    assert response.status_code == 403


def test_missing_authorization_header_is_rejected(client) -> None:
    test_client, _ = client

    response = test_client.get("/protected")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("authorization", ["Basic abc", "Bearer", "bearer "])
def test_malformed_bearer_header_is_rejected(client, authorization: str) -> None:
    test_client, _ = client

    response = test_client.get("/protected", headers={"Authorization": authorization})

    assert response.status_code == 401
