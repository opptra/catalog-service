from uuid import UUID

from pydantic import BaseModel, Field


class CreateJobAttribute(BaseModel):
    attribute_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1)


class CreateJobRequest(BaseModel):
    sku_ids: list[int] = Field(min_length=1)
    marketplace_id: int = Field(gt=0)
    attributes: list[CreateJobAttribute] = Field(min_length=1)


class CreatedSkuJob(BaseModel):
    sku_id: int
    external_id: UUID


class CreateJobResponse(BaseModel):
    external_id: UUID
    status: str
    marketplace_id: int
    sku_ids: list[int]
    sku_jobs: list[CreatedSkuJob]
    attribute_ids: list[int]
    workflow_execution: str | None = None


class CompleteJobResponse(BaseModel):
    external_id: UUID
    status: str
