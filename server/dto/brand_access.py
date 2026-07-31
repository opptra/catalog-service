from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BrandAccessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_id: UUID
    name: str
    granted_at: datetime
