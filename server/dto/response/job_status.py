from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from dto.marketplace_attribute_config import MarketplaceAttributeConfig


class JobExpectedAttributeResponse(BaseModel):
    attribute_external_id: UUID
    name: str
    data_type: str
    quantity: int
    group_label: str | None = None
    config: MarketplaceAttributeConfig | None = None


class JobSkuGenerationStatusItem(BaseModel):
    external_id: UUID
    sku_id: str
    display_name: str | None = None
    status: str
    tasks: dict[str, Any]


class JobStatusResponse(BaseModel):
    external_id: UUID
    job_group_id: UUID | None = None
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


class JobGroupMarketplaceStatus(BaseModel):
    """One marketplace job inside a job group (drives preview tabs)."""

    job_external_id: UUID
    marketplace_external_id: UUID
    marketplace_name: str
    status: str


class JobGroupStatusResponse(BaseModel):
    """Aggregated status for a multi-marketplace execution group."""

    job_group_id: UUID
    status: str
    started_at: datetime
    updated_at: datetime
    brand_external_id: UUID | None = None
    created_by_name: str | None = None
    sku_count: int
    completed_sku_count: int
    failed_sku_count: int
    pending_sku_count: int
    marketplaces: list[JobGroupMarketplaceStatus]
    # Active job payload (first marketplace, or the one requested via query).
    active_job: JobStatusResponse | None = None


class JobListMarketplaceItem(BaseModel):
    external_id: UUID
    name: str
    status: str


class JobListItemResponse(BaseModel):
    """Summary row for the brand execution history list (one row per job group)."""

    # Group key used by preview URL — COALESCE(job_group_id, job.external_id).
    job_group_id: UUID
    external_id: UUID = Field(
        description="Same as job_group_id (kept for clients that navigate on external_id).",
    )
    status: str
    started_at: datetime
    updated_at: datetime
    brand_external_id: UUID | None = None
    marketplace_name: str | None = None
    marketplaces: list[JobListMarketplaceItem] = Field(default_factory=list)
    category_name: str | None = None
    created_by_name: str | None = None
    execution_number: int
    sku_count: int
    completed_sku_count: int
    failed_sku_count: int
    pending_sku_count: int


class JobListResponse(BaseModel):
    items: list[JobListItemResponse]
    next_offset: int | None = None
    has_more: bool = False


class ImageVerificationMismatchResponse(BaseModel):
    """One on-image claim or look that disagrees with catalog / source photos."""

    model_config = ConfigDict(extra="ignore")

    kind: str
    source_field: str | None = None
    catalog: str | None = None
    observed: str | None = None


class ImageVerificationAxesResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    identity: int | None = None
    claims: int | None = None
    quality: int | None = None


class ImageVerificationSlotContextResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    role: str | None = None
    kind: str | None = None


class ImageVerificationSnapshotResponse(BaseModel):
    """One verification attempt — current, or the replaced first pass."""

    model_config = ConfigDict(extra="ignore")

    v: int
    status: str
    model: str
    attempt: int
    confidence: int | None = None
    threshold: int | None = None
    reasoning: str | None = None
    observed_text: list[str] | None = None
    mismatches: list[ImageVerificationMismatchResponse] | None = None
    axes: ImageVerificationAxesResponse | None = None
    slot: ImageVerificationSlotContextResponse | None = None
    error: str | None = None


class ImageVerificationResponse(ImageVerificationSnapshotResponse):
    """Per-version snapshot of product-data verification for an image slot."""

    previous: ImageVerificationSnapshotResponse | None = None


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
    # Unique brief for this version (v1 = slot/strategy brief; later = this regen's user note).
    prompt: str | None = None
    verification: ImageVerificationResponse | None = None


class RegenerateAttributeValueResponse(BaseModel):
    """Newest version after a successful regenerate or restore."""

    value_external_id: UUID
    attribute_external_id: UUID
    name: str
    data_type: str
    slot: int
    version: int
    value: str
    value_is_signed_url: bool
    prompt: str | None = None
    verification: ImageVerificationResponse | None = None


class SkuGenerationJobContentResponse(BaseModel):
    external_id: UUID
    job_external_id: UUID
    job_group_id: UUID | None = None
    sku_id: str
    display_name: str | None = None
    status: str
    tasks: dict[str, Any]
    marketplace_external_id: UUID | None = None
    marketplace_name: str | None = None
    attributes: list[SkuGenerationJobAttributeSlotResponse]


class SkuProductImageResponse(BaseModel):
    filename: str
    url: str


class SkuProductImagesResponse(BaseModel):
    sku_id: str
    images: list[SkuProductImageResponse]
