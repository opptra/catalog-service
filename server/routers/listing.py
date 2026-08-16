"""Listing fill API — export a filled Amazon workbook for a generation job."""

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
    """Fill the category listing template using values from a generation job."""
    try:
        authorization.assert_job_access(
            user_session,
            catalog_session,
            actor=user,
            job_external_id=body.job_external_id,
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
        return listing_service.fill_listing_for_job(
            catalog_session,
            gcs,
            dropbox,
            openrouter,
            body.job_external_id,
        )
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ListingTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ListingFillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (GcsError, DropboxError, OpenRouterError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
