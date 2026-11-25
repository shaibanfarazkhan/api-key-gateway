"""Tests for the administrative HTTP API."""

import hashlib
import os
from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# The application creates a configured engine during import. Keep this test
# process independent of a PostgreSQL service by selecting SQLite first.
os.environ["DATABASE_URL"] = "sqlite://"

from app.core.config import get_settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.core.dependencies import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import APIKey, AuditLog  # noqa: E402


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Provide a fresh in-memory database for each API test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with test_session() as session:
            yield session

    settings = get_settings()
    previous_admin_key = settings.admin_api_key
    settings.admin_api_key = SecretStr("test-admin-key")

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(
        app, headers={"Authorization": "Bearer test-admin-key"}
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    settings.admin_api_key = previous_admin_key
    engine.dispose()


def test_admin_route_accepts_authorized_admin(client: TestClient) -> None:
    response = client.get(
        "/admin/organizations", headers={"Authorization": "Bearer test-admin-key"}
    )
    assert response.status_code == 200


def test_admin_route_rejects_unauthenticated_request(client: TestClient) -> None:
    response = client.get("/admin/organizations", headers={"Authorization": ""})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_admin_route_forbids_invalid_admin_key(client: TestClient) -> None:
    response = client.get(
        "/admin/organizations", headers={"Authorization": "Bearer wrong-key"}
    )
    assert response.status_code == 403


def test_admin_route_fails_closed_when_admin_key_is_unconfigured(
    client: TestClient,
) -> None:
    settings = get_settings()
    settings.admin_api_key = None
    response = client.get(
        "/admin/organizations", headers={"Authorization": "Bearer test-admin-key"}
    )
    assert response.status_code == 503


def test_organization_create_list_get_and_duplicate_slug(client: TestClient) -> None:
    created = client.post(
        "/admin/organizations", json={"name": " Example Org ", "slug": "example-org"}
    )
    assert created.status_code == 201
    organization = created.json()
    assert organization["name"] == "Example Org"

    listed = client.get("/admin/organizations")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [organization["id"]]

    fetched = client.get(f"/admin/organizations/{organization['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["slug"] == "example-org"

    duplicate = client.post(
        "/admin/organizations", json={"name": "Another Org", "slug": "example-org"}
    )
    assert duplicate.status_code == 409


def test_organization_and_plan_missing_return_404(client: TestClient) -> None:
    missing_id = "00000000-0000-0000-0000-000000000001"
    assert client.get(f"/admin/organizations/{missing_id}").status_code == 404
    assert (
        client.patch(
            f"/admin/organizations/{missing_id}/plan",
            json={"plan_id": missing_id},
        ).status_code
        == 404
    )


def test_plan_create_and_assign(client: TestClient) -> None:
    organization_response = client.post(
        "/admin/organizations", json={"name": "Example", "slug": "example"}
    )
    plan_response = client.post(
        "/admin/plans",
        json={
            "name": "Standard",
            "requests_per_minute": 60,
            "monthly_quota": 10000,
        },
    )
    assert organization_response.status_code == 201
    assert plan_response.status_code == 201

    assignment = client.patch(
        f"/admin/organizations/{organization_response.json()['id']}/plan",
        json={"plan_id": plan_response.json()["id"]},
    )
    assert assignment.status_code == 200
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    audit_log = db.query(AuditLog).one()
    assert audit_log.event_type == "organization.plan_assigned"
    assert audit_log.organization_id == UUID(organization_response.json()["id"])
    assert audit_log.details["plan_id"] == plan_response.json()["id"]
    db_generator.close()


def test_api_key_create_rotate_and_revoke(client: TestClient) -> None:
    organization_response = client.post(
        "/admin/organizations", json={"name": "Example", "slug": "example"}
    )
    organization_id = organization_response.json()["id"]

    created = client.post("/admin/api-keys", json={"organization_id": organization_id})
    assert created.status_code == 201
    original = created.json()
    assert original["api_key"].startswith(original["prefix"])

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    stored_key = db.scalar(select(APIKey).where(APIKey.id == UUID(original["id"])))
    assert stored_key is not None
    assert (
        stored_key.key_hash
        == hashlib.sha256(original["api_key"].encode("utf-8")).hexdigest()
    )
    assert stored_key.key_hash != original["api_key"]
    creation_event = db.scalar(
        select(AuditLog).where(AuditLog.event_type == "api_key.created")
    )
    assert creation_event is not None
    assert creation_event.resource_id == stored_key.id
    assert original["api_key"] not in str(creation_event.details)
    db_generator.close()

    rotated = client.post(f"/admin/api-keys/{original['id']}/rotate")
    assert rotated.status_code == 201
    replacement = rotated.json()
    assert replacement["rotated_from_id"] == original["id"]
    assert replacement["api_key"] != original["api_key"]
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    stored_original = db.get(APIKey, UUID(original["id"]))
    assert stored_original is not None
    assert stored_original.status == "active"
    assert stored_original.rotation_expires_at is not None
    assert stored_original.rotation_expires_at > stored_original.created_at
    rotation_event = db.scalar(
        select(AuditLog).where(AuditLog.event_type == "api_key.rotated")
    )
    assert rotation_event is not None
    assert rotation_event.details["previous_key_id"] == original["id"]
    db_generator.close()
    assert client.get(f"/admin/organizations/{organization_id}").status_code == 200
    revoked = client.post(f"/admin/api-keys/{original['id']}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["revoked_at"] is not None
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    revocation_event = db.scalar(
        select(AuditLog).where(AuditLog.event_type == "api_key.revoked")
    )
    assert revocation_event is not None
    assert revocation_event.resource_id == UUID(original["id"])
    db_generator.close()


def test_repeated_rotation_does_not_extend_existing_overlap(client: TestClient) -> None:
    organization = client.post(
        "/admin/organizations", json={"name": "Example", "slug": "example"}
    ).json()
    created = client.post(
        "/admin/api-keys", json={"organization_id": organization["id"]}
    ).json()
    first_rotation = client.post(f"/admin/api-keys/{created['id']}/rotate")
    assert first_rotation.status_code == 201

    second_rotation = client.post(f"/admin/api-keys/{created['id']}/rotate")
    assert second_rotation.status_code == 409


def test_api_key_for_unknown_organization_returns_404(client: TestClient) -> None:
    response = client.post(
        "/admin/api-keys",
        json={"organization_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert response.status_code == 404
