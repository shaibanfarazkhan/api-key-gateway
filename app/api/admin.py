"""Administrative API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.models import APIKey, Organization, Plan
from app.schemas.admin import (
    APIKeyCreate,
    APIKeyCreated,
    APIKeyResponse,
    OrganizationCreate,
    OrganizationPlanUpdate,
    OrganizationResponse,
    PlanCreate,
    PlanResponse,
)
from app.services.admin import APIKeyService, OrganizationService, PlanService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/organizations",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_organization(
    payload: OrganizationCreate, db: Annotated[Session, Depends(get_db)]
) -> Organization:
    return OrganizationService(db).create(name=payload.name, slug=payload.slug)


@router.get("/organizations", response_model=list[OrganizationResponse])
def list_organizations(
    db: Annotated[Session, Depends(get_db)],
) -> list[Organization]:
    return OrganizationService(db).list()


@router.get("/organizations/{organization_id}", response_model=OrganizationResponse)
def get_organization(
    organization_id: UUID, db: Annotated[Session, Depends(get_db)]
) -> Organization:
    return OrganizationService(db).get(organization_id)


@router.post("/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def create_plan(payload: PlanCreate, db: Annotated[Session, Depends(get_db)]) -> Plan:
    return PlanService(db).create(**payload.model_dump())


@router.patch(
    "/organizations/{organization_id}/plan", response_model=OrganizationResponse
)
def assign_plan(
    organization_id: UUID,
    payload: OrganizationPlanUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> Organization:
    return OrganizationService(db).assign_plan(organization_id, payload.plan_id)


@router.post(
    "/api-keys", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED
)
def create_api_key(
    payload: APIKeyCreate, db: Annotated[Session, Depends(get_db)]
) -> APIKeyCreated:
    key, plaintext = APIKeyService(db).create(
        payload.organization_id,
        expires_at=payload.expires_at,
    )
    return APIKeyCreated(
        **APIKeyResponse.model_validate(key).model_dump(), api_key=plaintext
    )


@router.post(
    "/api-keys/{key_id}/rotate",
    response_model=APIKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
def rotate_api_key(
    key_id: UUID, db: Annotated[Session, Depends(get_db)]
) -> APIKeyCreated:
    key, plaintext = APIKeyService(db).rotate(key_id)
    return APIKeyCreated(
        **APIKeyResponse.model_validate(key).model_dump(), api_key=plaintext
    )


@router.post("/api-keys/{key_id}/revoke", response_model=APIKeyResponse)
def revoke_api_key(key_id: UUID, db: Annotated[Session, Depends(get_db)]) -> APIKey:
    return APIKeyService(db).revoke(key_id)
