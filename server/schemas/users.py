from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_id: str
    email: str | None
    name: str | None
    created_at: datetime
    updated_at: datetime
