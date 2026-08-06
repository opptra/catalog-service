from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AccessibleBrandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_id: UUID
    name: str
    granted_at: datetime


class BrandUserResponse(BaseModel):
    external_id: UUID
    name: str
    email: str
    granted_at: datetime
    has_signed_in: bool


class InviteBrandUserResponse(BaseModel):
    external_id: UUID
    name: str
    email: str
    granted_at: datetime
    has_signed_in: bool
    created: bool
