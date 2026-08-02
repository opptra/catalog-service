from uuid import UUID

from fastapi import APIRouter, HTTPException

from core.deps import CatalogSessionDep, CurrentUserDep, OpenRouterDep
from core.exceptions import (
    CategoryIntelligenceMissingError,
    ProductNotFoundError,
    SkuJobNotFoundError,
)
from dto.sku_job import SkuJobExecutionResponse
from services import job as job_service

# Generic jobs router. Job-kind-specific routes live under their own sub-prefix
# (e.g. SKU jobs under /jobs/sku/...), so new job kinds can be added here.
router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/sku/{external_id}/execute", response_model=SkuJobExecutionResponse)
def execute_sku_job(
    external_id: UUID,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    openrouter: OpenRouterDep,
) -> SkuJobExecutionResponse:
    try:
        summary = job_service.execute_sku_job(catalog_session, openrouter, external_id)
    except SkuJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CategoryIntelligenceMissingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SkuJobExecutionResponse.model_validate(summary)
