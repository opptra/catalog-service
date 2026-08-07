from uuid import UUID

from fastapi import HTTPException, Query

from core.auth import SecureAPIRouter, internal_api
from core.deps import CatalogSessionDep, CurrentUserDep, GcsDep, OpenRouterDep, WorkflowsDep
from core.exceptions import (
    AttributeNotFoundError,
    BrandDnaMissingError,
    BrandNotFoundError,
    CategoryIntelligenceMissingError,
    CategoryNotFoundError,
    FlatfileUploadIncompleteError,
    FlatfileValidationError,
    GcsError,
    InvalidJobAttributesError,
    JobNotFoundError,
    MarketplaceNotFoundError,
    ProductNotFoundError,
    SkuGenerationJobExecutionFailedError,
    SkuGenerationJobNotFoundError,
    SkuNotFoundError,
    WorkflowsError,
)
from dto.request.job import (
    CreateFlatfileJobRequest,
    CreateJobRequest,
)
from dto.response.job import (
    CompleteFlatfileJobResponse,
    CompleteJobResponse,
    CreateFlatfileJobResponse,
    CreateJobResponse,
)
from dto.response.job_status import (
    JobListResponse,
    JobStatusResponse,
    SkuGenerationJobContentResponse,
)
from dto.response.sku_generation_job import SkuGenerationJobExecutionResponse
from services import job as job_service

# All job kinds live here. Kind-specific routes use a sub-prefix
# (e.g. /jobs/sku/..., /jobs/flatfile/...).
# Static path segments (/sku/..., /flatfile/...) must be registered before
# parameterized /{external_id}/... routes.
router = SecureAPIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=JobListResponse)
def list_jobs(
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    brand_external_id: UUID = Query(...),
) -> JobListResponse:
    """Execution history for the current user in a brand workspace."""
    try:
        listed = job_service.list_jobs(
            catalog_session,
            created_by=user.external_id,
            brand_external_id=brand_external_id,
        )
    except BrandNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return JobListResponse.model_validate(listed)


@router.get("/sku/{external_id}", response_model=SkuGenerationJobContentResponse)
def get_sku_generation_job_content(
    external_id: UUID,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    gcs: GcsDep,
) -> SkuGenerationJobContentResponse:
    """Attribute slots for one SKU generation job (IMAGE values as signed URLs)."""
    try:
        content = job_service.get_sku_generation_job_content(
            catalog_session,
            gcs,
            external_id,
            created_by=user.external_id,
        )
    except SkuGenerationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GcsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SkuGenerationJobContentResponse.model_validate(content)


@router.get("/{external_id}/status", response_model=JobStatusResponse)
def get_job_status(
    external_id: UUID,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
) -> JobStatusResponse:
    """Poll overall generation progress for a job (no content payloads)."""
    try:
        status = job_service.get_job_status(
            catalog_session,
            external_id,
            created_by=user.external_id,
        )
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return JobStatusResponse.model_validate(status)


@router.post("", response_model=CreateJobResponse)
def create_job(
    body: CreateJobRequest,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    workflows: WorkflowsDep,
) -> CreateJobResponse:
    """Create a job for one or more SKUs, then start the Cloud Workflows pipeline."""
    try:
        created = job_service.create_job(
            catalog_session,
            workflows,
            created_by=user.external_id,
            sku_ids=body.sku_ids,
            brand_external_id=body.brand_external_id,
            marketplace_external_id=body.marketplace_external_id,
            attributes=[
                (item.attribute_external_id, item.quantity) for item in body.attributes
            ],
        )
    except BrandNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MarketplaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SkuNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AttributeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidJobAttributesError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WorkflowsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return CreateJobResponse.model_validate(created)


@router.post("/flatfile", response_model=CreateFlatfileJobResponse)
def create_flatfile_job(
    body: CreateFlatfileJobRequest,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    gcs: GcsDep,
) -> CreateFlatfileJobResponse:
    try:
        created = job_service.create_flatfile_job(
            catalog_session,
            gcs,
            created_by=user.external_id,
            brand_external_id=body.brand_external_id,
            category_external_id=body.category_external_id,
            template_filename=body.template_filename,
            template_content_type=body.template_content_type,
            images=[item.model_dump() for item in body.images],
        )
    except BrandNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CategoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FlatfileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return CreateFlatfileJobResponse.model_validate(created)


@router.post(
    "/flatfile/{external_id}/complete",
    response_model=CompleteFlatfileJobResponse,
)
def complete_flatfile_job(
    external_id: UUID,
    catalog_session: CatalogSessionDep,
    gcs: GcsDep,
) -> CompleteFlatfileJobResponse:
    try:
        completed = job_service.complete_flatfile_job(catalog_session, gcs, external_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CategoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SkuNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FlatfileUploadIncompleteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FlatfileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return CompleteFlatfileJobResponse.model_validate(completed)


@router.post(
    "/sku/{external_id}/execute",
    response_model=SkuGenerationJobExecutionResponse,
)
@internal_api
def execute_sku_generation_job(
    external_id: UUID,
    catalog_session: CatalogSessionDep,
    openrouter: OpenRouterDep,
    gcs: GcsDep,
) -> SkuGenerationJobExecutionResponse:
    try:
        summary = job_service.execute_sku_generation_job(
            catalog_session,
            openrouter,
            gcs,
            external_id,
        )
    except SkuGenerationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BrandNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CategoryIntelligenceMissingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BrandDnaMissingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GcsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SkuGenerationJobExecutionFailedError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SkuGenerationJobExecutionResponse.model_validate(summary)


@router.post("/{external_id}/complete", response_model=CompleteJobResponse)
@internal_api
def complete_job(
    external_id: UUID,
    catalog_session: CatalogSessionDep,
) -> CompleteJobResponse:
    """Mark the parent job COMPLETED after all SKU generation jobs succeed (workflow callback)."""
    try:
        completed = job_service.complete_job(catalog_session, external_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return CompleteJobResponse.model_validate(completed)
