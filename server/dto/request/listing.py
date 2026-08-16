from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FillListingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_external_id: UUID
