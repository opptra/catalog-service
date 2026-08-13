from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ListingFillGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: str
    column_label: str
    reason: str


class FillListingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_external_id: UUID
    filled_file_url: str
    gaps: list[ListingFillGap] = Field(default_factory=list)
