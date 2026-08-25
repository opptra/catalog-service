from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FillListingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_group_id: UUID
    marketplace_external_id: UUID
