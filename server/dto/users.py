from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: UUID
    email: str | None
    name: str | None
    created_at: datetime
    updated_at: datetime
