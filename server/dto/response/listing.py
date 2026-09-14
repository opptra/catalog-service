from datetime import datetime
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
    """Result of a completed fill run (GCS upload + gaps). Used by the worker."""

    model_config = ConfigDict(extra="forbid")

    job_external_id: UUID
    filled_file_url: str
    gaps: list[ListingFillGap] = Field(default_factory=list)


class StartListingFillResponse(BaseModel):
    """Ack from POST /listings/fill — fill runs in the background."""

    model_config = ConfigDict(extra="forbid")

    status: str
    job_external_id: UUID
    sku_count: int
    estimated_minutes: int
    message: str


class JobGroupListingFileItem(BaseModel):
    """Latest filled listing workbook for one marketplace in a job group."""

    model_config = ConfigDict(extra="forbid")

    marketplace_external_id: UUID
    marketplace_name: str
    job_external_id: UUID
    filename: str | None = None
    filled_file_url: str | None = None
    generated_at: datetime | None = None
    gaps: list[ListingFillGap] = Field(default_factory=list)


class JobGroupListingFilesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_group_id: UUID
    files: list[JobGroupListingFileItem] = Field(default_factory=list)
