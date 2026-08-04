from uuid import UUID

from pydantic import BaseModel


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
