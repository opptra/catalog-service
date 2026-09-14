"""Listing fill API — export a filled listing workbook for a generation job group."""

from fastapi import BackgroundTasks, HTTPException, Request

from core.auth import SecureAPIRouter
from core.deps import (
    CatalogSessionDep,
    CurrentUserDep,
    DropboxDep,
    GcsDep,
    OpenRouterDep,
    UserSessionDep,
)
from core.exceptions import (
    ApplicationNotFoundError,
    BrandAccessDeniedError,
    BrandNotFoundError,
    JobNotFoundError,
    ListingFillError,
    ListingTemplateNotFoundError,
    UserServiceBrandNotFoundError,
)
from dto.request.listing import FillListingRequest
from dto.response.listing import StartListingFillResponse
from services import authorization
from services import listing as listing_service

router = SecureAPIRouter(prefix="/listings", tags=["listings"])


@router.post("/fill", response_model=StartListingFillResponse, status_code=202)
def fill_listing(
    body: FillListingRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    user_session: UserSessionDep,
    gcs: GcsDep,
    dropbox: DropboxDep,
    openrouter: OpenRouterDep,
) -> StartListingFillResponse:
    """Start filling the listing template; return immediately with an estimate."""
    try:
        authorization.assert_job_group_access(
            user_session,
            catalog_session,
            actor=user,
            job_group_id=body.job_group_id,
        )
    except BrandAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (
        BrandNotFoundError,
        UserServiceBrandNotFoundError,
        JobNotFoundError,
    ) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        ack, started = listing_service.start_listing_fill_for_group(
            catalog_session,
            job_group_id=body.job_group_id,
            marketplace_external_id=body.marketplace_external_id,
        )
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ListingTemplateNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ListingFillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if started:
        background_tasks.add_task(
            listing_service.run_listing_fill_background,
            request.app.state.catalog_db.session_factory,
            gcs,
            dropbox,
            openrouter,
            ack.job_external_id,
        )

    return ack
