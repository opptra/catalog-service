"""Listing fill API — export a filled listing workbook for a generation job group."""

from fastapi import HTTPException

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
    DropboxError,
    GcsError,
    JobNotFoundError,
    ListingFillError,
    ListingTemplateNotFoundError,
    OpenRouterError,
    UserServiceBrandNotFoundError,
)
from dto.request.listing import FillListingRequest
from dto.response.listing import FillListingResponse
from services import authorization
from services import listing as listing_service

router = SecureAPIRouter(prefix="/listings", tags=["listings"])


@router.post("/fill", response_model=FillListingResponse)
def fill_listing(
    body: FillListingRequest,
    user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    user_session: UserSessionDep,
    gcs: GcsDep,
    dropbox: DropboxDep,
    openrouter: OpenRouterDep,
) -> FillListingResponse:
    """Fill the category listing template for the selected marketplace in a job group."""
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
        return listing_service.fill_listing_for_group(
            catalog_session,
            gcs,
            dropbox,
            openrouter,
            job_group_id=body.job_group_id,
            marketplace_external_id=body.marketplace_external_id,
        )
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ListingTemplateNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ListingFillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (GcsError, DropboxError, OpenRouterError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
