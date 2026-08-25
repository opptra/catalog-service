from uuid import UUID

from pydantic import BaseModel


class CreatedSkuGenerationJob(BaseModel):
    sku_id: str
    external_id: UUID


class CreateJobChildResponse(BaseModel):
    """One marketplace job created as part of a multi-marketplace group."""

    external_id: UUID
    job_group_id: UUID
    status: str
    marketplace_external_id: UUID
    marketplace_name: str | None = None
    sku_ids: list[str]
    sku_generation_jobs: list[CreatedSkuGenerationJob]
    attribute_external_ids: list[UUID]
    workflow_execution: str | None = None


class CreateJobResponse(BaseModel):
    """Response after creating one or more marketplace jobs that share a group id."""

    job_group_id: UUID
    jobs: list[CreateJobChildResponse]
    sku_ids: list[str]


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
