from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class JobExpectedAttributeResponse(BaseModel):
    attribute_external_id: UUID
    name: str
    data_type: str
    quantity: int
    group_label: str | None = None


class JobSkuGenerationStatusItem(BaseModel):
    external_id: UUID
    sku_id: str
    display_name: str | None = None
    status: str
    tasks: dict[str, Any]


class JobStatusResponse(BaseModel):
    external_id: UUID
    status: str
    started_at: datetime
    updated_at: datetime
    brand_external_id: UUID | None = None
    marketplace_external_id: UUID | None = None
    marketplace_name: str | None = None
    category_external_id: UUID | None = None
    category_name: str | None = None
    sku_count: int
    completed_sku_count: int
    failed_sku_count: int
    pending_sku_count: int
    expected_attributes: list[JobExpectedAttributeResponse]
    sku_generation_jobs: list[JobSkuGenerationStatusItem]


class JobListItemResponse(BaseModel):
    """Summary row for the brand execution history list."""

    external_id: UUID
    status: str
    started_at: datetime
    updated_at: datetime
    brand_external_id: UUID | None = None
    marketplace_name: str | None = None
    category_name: str | None = None
    sku_count: int
    completed_sku_count: int
    failed_sku_count: int
    pending_sku_count: int


class JobListResponse(BaseModel):
    items: list[JobListItemResponse]


class SkuGenerationJobAttributeSlotResponse(BaseModel):
    attribute_external_id: UUID
    name: str
    data_type: str
    slot: int
    quantity: int
    task_status: str
    value_external_id: UUID | None = None
    version: int | None = None
    # Text content, or a signed HTTPS URL for IMAGE attributes.
    value: str | None = None
    value_is_signed_url: bool = False


class SkuGenerationJobContentResponse(BaseModel):
    external_id: UUID
    job_external_id: UUID
    sku_id: str
    display_name: str | None = None
    status: str
    tasks: dict[str, Any]
    marketplace_external_id: UUID | None = None
    marketplace_name: str | None = None
    attributes: list[SkuGenerationJobAttributeSlotResponse]
