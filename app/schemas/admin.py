"""Request and response schemas for administrative resources."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    status: str
    created_at: datetime
    updated_at: datetime


class PlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    requests_per_minute: int = Field(ge=0)
    monthly_quota: int = Field(ge=0)
    active: bool = True

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    requests_per_minute: int
    monthly_quota: int
    active: bool
    created_at: datetime
    updated_at: datetime


class OrganizationPlanUpdate(BaseModel):
    plan_id: UUID


class APIKeyCreate(BaseModel):
    organization_id: UUID
    expires_at: datetime | None = None


class APIKeyResponse(BaseModel):
    id: UUID
    organization_id: UUID
    prefix: str
    status: str
    expires_at: datetime | None
    rotated_from_id: UUID | None
    created_at: datetime
    revoked_at: datetime | None


class APIKeyCreated(APIKeyResponse):
    """One-time response containing the only plaintext copy of a new key."""

    api_key: str
