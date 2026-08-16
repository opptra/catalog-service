"""Response DTOs for job content export (UI builds the sheet)."""

from uuid import UUID

from pydantic import BaseModel, Field


class JobContentExportColumn(BaseModel):
    key: str
    label: str
    data_type: str


class JobContentExportResponse(BaseModel):
    job_external_id: UUID
    marketplace_external_id: UUID | None = None
    marketplace_name: str | None = None
    columns: list[JobContentExportColumn]
    rows: list[dict[str, str | None]] = Field(default_factory=list)
