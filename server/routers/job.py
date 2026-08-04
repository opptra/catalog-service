from uuid import UUID

from fastapi import HTTPException

from core.auth import SecureAPIRouter, internal_api
from core.deps import CatalogSessionDep, CurrentUserDep, GcsDep, OpenRouterDep, WorkflowsDep
from core.exceptions import (
    AttributeNotFoundError,
    CategoryIntelligenceMissingError,
    GcsError,
    InvalidJobAttributesError,
    JobNotFoundError,
    MarketplaceNotFoundError,
    ProductNotFoundError,
    SkuJobExecutionFailedError,
    SkuJobNotFoundError,
    SkuNotFoundError,
    WorkflowsError,
)
from dto.request.job import CreateJobRequest
from dto.response.job import CompleteJobResponse, CreateJobResponse
from dto.response.sku_job import SkuJobExecutionResponse
from services import job as job_service

# Generic jobs router. Job-kind-specific routes live under their own sub-prefix
# (e.g. SKU jobs under /jobs/sku/...), so new job kinds can be added here.
router = SecureAPIRouter(prefix="/jobs", tags=["jobs"])


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
            marketplace_id=body.marketplace_id,
            attributes=[(item.attribute_id, item.quantity) for item in body.attributes],
        )
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


@router.post("/sku/{external_id}/execute", response_model=SkuJobExecutionResponse)
@internal_api
def execute_sku_job(
    external_id: UUID,
    catalog_session: CatalogSessionDep,
    openrouter: OpenRouterDep,
    gcs: GcsDep,
) -> SkuJobExecutionResponse:
    try:
        summary = job_service.execute_sku_job(catalog_session, openrouter, gcs, external_id)
    except SkuJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CategoryIntelligenceMissingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GcsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SkuJobExecutionFailedError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SkuJobExecutionResponse.model_validate(summary)


@router.post("/{external_id}/complete", response_model=CompleteJobResponse)
@internal_api
def complete_job(
    external_id: UUID,
    catalog_session: CatalogSessionDep,
) -> CompleteJobResponse:
    """Mark the parent job COMPLETED after all SKU jobs succeed (workflow callback)."""
    try:
        completed = job_service.complete_job(catalog_session, external_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return CompleteJobResponse.model_validate(completed)
