from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.auth import SecureAPIRouter, internal_api
from core.deps import (
    BrandAccessDep,
    CatalogSessionDep,
    CurrentUserDep,
    DropboxDep,
    GcsDep,
    OpenRouterDep,
    UserSessionDep,
    WorkflowsDep,
)
from core.exceptions import (
    ApplicationNotFoundError,
    AttributeNotFoundError,
    AttributeValueNotFoundError,
    AttributeValuePromptMissingError,
    AttributeValueRegenerationError,
    BrandAccessDeniedError,
    BrandDnaMissingError,
    BrandNotFoundError,
    CategoryIntelligenceMissingError,
    CategoryNotFoundError,
    DropboxError,
    FlatfileUploadIncompleteError,
    FlatfileValidationError,
    GcsError,
    InvalidJobAttributesError,
    JobNotFoundError,
    MarketplaceNotFoundError,
    ProductNotFoundError,
    SkuGenerationJobExecutionFailedError,
    SkuGenerationJobNotFoundError,
    SkuGenerationJobRetryConflictError,
    SkuNotFoundError,
    UserServiceBrandNotFoundError,
    WorkflowsError,
)
from dto.request.job import (
    CreateFlatfileJobRequest,
    CreateJobRequest,
    RegenerateAttributeValueRequest,
    RestoreAttributeValueRequest,
)
from dto.response.content_export import JobContentExportResponse
from dto.response.job import (
    CompleteFlatfileJobResponse,
    CompleteJobResponse,
    CreateFlatfileJobResponse,
    CreateJobResponse,
)
from dto.response.job_status import (
    JobListResponse,
    JobStatusResponse,
    RegenerateAttributeValueResponse,
    SkuGenerationJobContentResponse,
    SkuProductImagesResponse,
)
from dto.response.sku_generation_job import SkuGenerationJobExecutionResponse
from entities.user_service.user import User
from services import authorization
from services import content_export as content_export_service
from services import job as job_service

# All job kinds live here. Kind-specific routes use a sub-prefix
# (e.g. /jobs/sku/..., /jobs/flatfile/...).
# Static path segments (/sku/..., /flatfile/...) must be registered before
# parameterized /{external_id}/... routes.
router = SecureAPIRouter(prefix="/jobs", tags=["jobs"])


def _map_brand_access_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, BrandAccessDeniedError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, (BrandNotFoundError, UserServiceBrandNotFoundError, JobNotFoundError)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, SkuGenerationJobNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AttributeValueNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ApplicationNotFoundError):
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _require_job_access(
    user_session: Session,
    catalog_session: Session,
    *,
    actor: User,
    job_external_id: UUID,
) -> None:
    try:
        authorization.assert_job_access(
            user_session,
            catalog_session,
            actor=actor,
            job_external_id=job_external_id,
        )
    except (
        BrandAccessDeniedError,
        BrandNotFoundError,
        UserServiceBrandNotFoundError,
        JobNotFoundError,
        ApplicationNotFoundError,
    ) as exc:
        raise _map_brand_access_errors(exc) from exc


def _require_sku_job_access(
    user_session: Session,
    catalog_session: Session,
    *,
    actor: User,
    sku_generation_job_external_id: UUID,
) -> None:
    try:
        authorization.assert_sku_generation_job_access(
            user_session,
            catalog_session,
            actor=actor,
            sku_generation_job_external_id=sku_generation_job_external_id,
        )
    except (
        BrandAccessDeniedError,
        BrandNotFoundError,
        UserServiceBrandNotFoundError,
        JobNotFoundError,
        SkuGenerationJobNotFoundError,
        ApplicationNotFoundError,
    ) as exc:
        raise _map_brand_access_errors(exc) from exc


def _require_attribute_value_access(
    user_session: Session,
    catalog_session: Session,
    *,
    actor: User,
    value_external_id: UUID,
) -> None:
    try:
        authorization.assert_attribute_value_access(
            user_session,
            catalog_session,
            actor=actor,
            value_external_id=value_external_id,
        )
    except (
        BrandAccessDeniedError,
        BrandNotFoundError,
        UserServiceBrandNotFoundError,
        JobNotFoundError,
        SkuGenerationJobNotFoundError,
        AttributeValueNotFoundError,
        ApplicationNotFoundError,
    ) as exc:
        raise _map_brand_access_errors(exc) from exc


@router.get("", response_model=JobListResponse)
def list_jobs(
    _user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    brand_external_id: BrandAccessDep,
) -> JobListResponse:
    """Brand-level execution history (all creators in the brand workspace)."""
    try:
        listed = job_service.list_jobs(
            catalog_session,
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
    user_session: UserSessionDep,
    gcs: GcsDep,
) -> SkuGenerationJobContentResponse:
    """Attribute slots for one SKU generation job (IMAGE values as signed URLs)."""
    _require_sku_job_access(
        user_session,
        catalog_session,
        actor=user,
        sku_generation_job_external_id=external_id,
    )
    try:
        content = job_service.get_sku_generation_job_content(
            catalog_session,
            gcs,
            external_id,
        )
    except SkuGenerationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GcsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SkuGenerationJobContentResponse.model_validate(content)


@router.get("/sku/{external_id}/product-images", response_model=SkuProductImagesResponse)
def get_sku_product_images(
    external_id: UUID,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    user_session: UserSessionDep,
    gcs: GcsDep,
) -> SkuProductImagesResponse:
    """Signed URLs for this SKU's source product photos in GCS."""
    _require_sku_job_access(
        user_session,
        catalog_session,
        actor=user,
        sku_generation_job_external_id=external_id,
    )
    try:
        listed = job_service.list_sku_product_images(catalog_session, gcs, external_id)
    except SkuGenerationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GcsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SkuProductImagesResponse.model_validate(listed)


@router.post(
    "/attribute-values/{external_id}/regenerate",
    response_model=RegenerateAttributeValueResponse,
)
def regenerate_attribute_value(
    external_id: UUID,
    body: RegenerateAttributeValueRequest,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    user_session: UserSessionDep,
    openrouter: OpenRouterDep,
    gcs: GcsDep,
) -> RegenerateAttributeValueResponse:
    """Revise the stored prompt with user notes and write a new value version."""
    _require_attribute_value_access(
        user_session,
        catalog_session,
        actor=user,
        value_external_id=external_id,
    )
    try:
        regenerated = job_service.regenerate_attribute_value(
            catalog_session,
            openrouter,
            gcs,
            value_external_id=external_id,
            improvement=body.improvement,
        )
    except AttributeValueNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AttributeValuePromptMissingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (
        AttributeNotFoundError,
        SkuGenerationJobNotFoundError,
        JobNotFoundError,
        BrandNotFoundError,
        ProductNotFoundError,
    ) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CategoryIntelligenceMissingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BrandDnaMissingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AttributeValueRegenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except GcsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return RegenerateAttributeValueResponse.model_validate(regenerated)


@router.post(
    "/attribute-values/{external_id}/restore",
    response_model=RegenerateAttributeValueResponse,
)
def restore_attribute_value(
    external_id: UUID,
    body: RestoreAttributeValueRequest,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    user_session: UserSessionDep,
    gcs: GcsDep,
) -> RegenerateAttributeValueResponse:
    """Copy an older version forward as the new latest (same external_id)."""
    _require_attribute_value_access(
        user_session,
        catalog_session,
        actor=user,
        value_external_id=external_id,
    )
    try:
        restored = job_service.restore_attribute_value_version(
            catalog_session,
            gcs,
            value_external_id=external_id,
            version=body.version,
        )
    except AttributeValueNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (AttributeNotFoundError, SkuGenerationJobNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GcsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return RegenerateAttributeValueResponse.model_validate(restored)


@router.get("/{external_id}/status", response_model=JobStatusResponse)
def get_job_status(
    external_id: UUID,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    user_session: UserSessionDep,
) -> JobStatusResponse:
    """Poll overall generation progress for a job (no content payloads)."""
    _require_job_access(
        user_session,
        catalog_session,
        actor=user,
        job_external_id=external_id,
    )
    try:
        status = job_service.get_job_status(
            catalog_session,
            external_id,
        )
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return JobStatusResponse.model_validate(status)


@router.get("/{external_id}/content-export", response_model=JobContentExportResponse)
def export_job_content(
    external_id: UUID,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    user_session: UserSessionDep,
    gcs: GcsDep,
    dropbox: DropboxDep,
) -> JobContentExportResponse:
    """Export generated content for all SKUs (dynamic columns; images as Dropbox URLs)."""
    _require_job_access(
        user_session,
        catalog_session,
        actor=user,
        job_external_id=external_id,
    )
    try:
        payload = content_export_service.export_job_content(
            catalog_session,
            gcs,
            dropbox,
            external_id,
        )
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (GcsError, DropboxError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return JobContentExportResponse.model_validate(payload)


@router.post("", response_model=CreateJobResponse)
def create_job(
    body: CreateJobRequest,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    brand_external_id: BrandAccessDep,
    workflows: WorkflowsDep,
) -> CreateJobResponse:
    """Create a job for one or more SKUs, then start the Cloud Workflows pipeline."""
    try:
        created = job_service.create_job(
            catalog_session,
            workflows,
            created_by=user.external_id,
            sku_ids=body.sku_ids,
            brand_external_id=brand_external_id,
            marketplace_external_id=body.marketplace_external_id,
            attributes=[(item.attribute_external_id, item.quantity) for item in body.attributes],
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
    brand_external_id: BrandAccessDep,
    gcs: GcsDep,
) -> CreateFlatfileJobResponse:
    try:
        created = job_service.create_flatfile_job(
            catalog_session,
            gcs,
            created_by=user.external_id,
            brand_external_id=brand_external_id,
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
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    user_session: UserSessionDep,
    gcs: GcsDep,
) -> CompleteFlatfileJobResponse:
    _require_job_access(
        user_session,
        catalog_session,
        actor=user,
        job_external_id=external_id,
    )
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


@router.post(
    "/sku/{external_id}/retry",
    response_model=SkuGenerationJobExecutionResponse,
)
def retry_sku_generation_job(
    external_id: UUID,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    user_session: UserSessionDep,
    openrouter: OpenRouterDep,
    gcs: GcsDep,
) -> SkuGenerationJobExecutionResponse:
    """User-triggered retry of a SKU job's PENDING/FAILED tasks (e.g. one failed attribute)."""
    _require_sku_job_access(
        user_session,
        catalog_session,
        actor=user,
        sku_generation_job_external_id=external_id,
    )
    try:
        summary = job_service.retry_sku_generation_job(
            catalog_session,
            openrouter,
            gcs,
            external_id,
        )
    except SkuGenerationJobRetryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        # Same mapping as /execute for the identical failure mode.
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
