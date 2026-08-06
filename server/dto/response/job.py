from uuid import UUID

from pydantic import BaseModel


class CreatedSkuGenerationJob(BaseModel):
    sku_id: int
    external_id: UUID


class CreateJobResponse(BaseModel):
    external_id: UUID
    status: str
    marketplace_id: int
    sku_ids: list[int]
    sku_generation_jobs: list[CreatedSkuGenerationJob]
    attribute_ids: list[int]
    workflow_execution: str | None = None


class CompleteJobResponse(BaseModel):
    external_id: UUID
    status: str


class SignedObjectUrl(BaseModel):
    object_key: str
    upload_url: str | None = None
    delete_url: str | None = None
    content_type: str | None = None
    sku_id: str | None = None
    filename: str | None = None


class CreateFlatfileJobResponse(BaseModel):
    external_id: UUID
    status: str
    template: SignedObjectUrl
    images: list[SignedObjectUrl]
    deletes: list[SignedObjectUrl]


class CompleteFlatfileJobResponse(BaseModel):
    external_id: UUID
    status: str
    sku_ids: list[str]
