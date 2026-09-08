from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from entities.catalog.attribute_enums import ListingFillGapReason


class ListingFillGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: str
    column_label: str
    reason: ListingFillGapReason
    message: str = ""

    @model_validator(mode="after")
    def _message_from_reason(self) -> "ListingFillGap":
        self.message = self.reason.message
        return self


class FillListingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_external_id: UUID
    filled_file_url: str
    gaps: list[ListingFillGap] = Field(default_factory=list)
