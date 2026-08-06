from uuid import UUID

from pydantic import BaseModel, Field


class CreateJobAttribute(BaseModel):
    attribute_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1)


class CreateJobRequest(BaseModel):
    sku_ids: list[int] = Field(min_length=1)
    marketplace_id: int = Field(gt=0)
    attributes: list[CreateJobAttribute] = Field(min_length=1)


class FlatfileImageFile(BaseModel):
    sku_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)


class CreateFlatfileJobRequest(BaseModel):
    category_external_id: UUID
    template_filename: str = Field(min_length=1)
    template_content_type: str = Field(min_length=1)
    images: list[FlatfileImageFile] = Field(min_length=1)
