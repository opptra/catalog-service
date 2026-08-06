from uuid import UUID

from pydantic import BaseModel, Field


class InviteBrandUserRequest(BaseModel):
    brand_external_id: UUID
    email: str = Field(min_length=3, max_length=320)
