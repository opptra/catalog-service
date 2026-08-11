from uuid import UUID

from pydantic import BaseModel, Field


class CreateJobAttribute(BaseModel):
    attribute_external_id: UUID
    quantity: int = Field(default=1, ge=1)


class CreateJobRequest(BaseModel):
    sku_ids: list[str] = Field(min_length=1)
    brand_external_id: UUID
    marketplace_external_id: UUID
    attributes: list[CreateJobAttribute] = Field(min_length=1)


class FlatfileImageFile(BaseModel):
    sku_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)


class CreateFlatfileJobRequest(BaseModel):
    brand_external_id: UUID
    category_external_id: UUID
    template_filename: str = Field(min_length=1)
    template_content_type: str = Field(min_length=1)
    images: list[FlatfileImageFile] = Field(min_length=1)


class RegenerateAttributeValueRequest(BaseModel):
    """User-facing improvement notes for regenerating one attribute value version."""

    improvement: str = Field(min_length=1, max_length=4000)


class RestoreAttributeValueRequest(BaseModel):
    """Re-promote an older version by copying it forward as a new latest version."""

    version: int = Field(ge=1)
