"""Job group routes — multi-marketplace execution preview and SKU image download."""

from typing import Annotated
from uuid import UUID

from fastapi import HTTPException, Query
from sqlalchemy.orm import Session

from core.auth import SecureAPIRouter
from core.deps import (
    CatalogSessionDep,
    CurrentUserDep,
    GcsDep,
    UserSessionDep,
)
from core.exceptions import (
    ApplicationNotFoundError,
    BrandAccessDeniedError,
    BrandNotFoundError,
    GcsError,
    JobNotFoundError,
    SkuNotFoundError,
    UserServiceBrandNotFoundError,
)
from dto.response.job_status import JobGroupStatusResponse
from dto.response.sku_image_export import SkuImageDownloadResponse
from entities.user_service.user import User
from services import authorization
from services import job as job_service
from services import sku_image_export as sku_image_export_service

router = SecureAPIRouter(prefix="/job-groups", tags=["job-groups"])


def _require_job_group_access(
    user_session: Session,
    catalog_session: Session,
    *,
    actor: User,
    job_group_id: UUID,
) -> None:
    try:
        authorization.assert_job_group_access(
            user_session,
            catalog_session,
            actor=actor,
            job_group_id=job_group_id,
        )
    except (
        BrandAccessDeniedError,
        BrandNotFoundError,
        UserServiceBrandNotFoundError,
        JobNotFoundError,
        ApplicationNotFoundError,
    ) as exc:
        if isinstance(exc, BrandAccessDeniedError):
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if isinstance(exc, ApplicationNotFoundError):
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{job_group_id}/status", response_model=JobGroupStatusResponse)
def get_job_group_status(
    job_group_id: UUID,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    user_session: UserSessionDep,
    marketplace_external_id: Annotated[UUID | None, Query()] = None,
) -> JobGroupStatusResponse:
    """Aggregated status for a multi-marketplace execution (drives preview tabs)."""
    _require_job_group_access(
        user_session,
        catalog_session,
        actor=user,
        job_group_id=job_group_id,
    )
    try:
        payload = job_service.get_job_group_status(
            catalog_session,
            user_session,
            job_group_id,
            marketplace_external_id=marketplace_external_id,
        )
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return JobGroupStatusResponse.model_validate(payload)


@router.get(
    "/{job_group_id}/skus/{sku_id}/images",
    response_model=SkuImageDownloadResponse,
)
def download_sku_images(
    job_group_id: UUID,
    sku_id: str,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    user_session: UserSessionDep,
    gcs: GcsDep,
) -> SkuImageDownloadResponse:
    """Signed URLs for generated PDP / A+ images across every marketplace in the group."""
    _require_job_group_access(
        user_session,
        catalog_session,
        actor=user,
        job_group_id=job_group_id,
    )
    try:
        payload = sku_image_export_service.list_sku_image_urls(
            catalog_session,
            gcs,
            job_group_id=job_group_id,
            sku_id=sku_id,
        )
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SkuNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GcsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SkuImageDownloadResponse.model_validate(payload)
