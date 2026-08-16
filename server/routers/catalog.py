"""Shared catalog UI data — categories and batch generation options."""

from typing import Annotated
from uuid import UUID

from fastapi import Form, HTTPException, Query, UploadFile

from core.auth import SecureAPIRouter, internal_api
from core.deps import CatalogSessionDep, CurrentUserDep, GcsDep
from core.exceptions import (
    AmbiguousCategoryError,
    CategoryNotFoundError,
    InvalidCategoryPathError,
    MarketplaceNotFoundError,
)
from dto.request.category import ImportCategoryPathRequest
from dto.response.catalog import MarketplaceSelectionResponse, UploadListingTemplateResponse
from dto.response.category import (
    CategoryTemplateResponse,
    ImportCategoryPathResponse,
    LeafCategoryPageResponse,
)
from services import catalog as catalog_service
from services.catalog import DEFAULT_LEAF_PAGE_SIZE

router = SecureAPIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/categories/leaves", response_model=LeafCategoryPageResponse)
def list_leaf_categories(
    _user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=DEFAULT_LEAF_PAGE_SIZE)] = DEFAULT_LEAF_PAGE_SIZE,
) -> LeafCategoryPageResponse:
    return catalog_service.list_leaf_categories(
        catalog_session,
        offset=offset,
        limit=limit,
    )


@router.post("/categories/import", response_model=ImportCategoryPathResponse)
@internal_api
def import_category_path(
    body: ImportCategoryPathRequest,
    catalog_session: CatalogSessionDep,
) -> ImportCategoryPathResponse:
    """Import a root-first category path, reusing existing nodes when possible.

    Idempotent: repeating the same path creates no new rows.
    """
    try:
        return catalog_service.import_category_path(catalog_session, body.categories)
    except InvalidCategoryPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AmbiguousCategoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/categories/{external_id}/template", response_model=CategoryTemplateResponse)
def get_category_template(
    external_id: UUID,
    _user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
) -> CategoryTemplateResponse:
    try:
        return catalog_service.get_category_template(catalog_session, external_id)
    except CategoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/listing-template",
    response_model=UploadListingTemplateResponse,
    summary="Upload a listing template for a category × marketplace",
)
@internal_api
def upload_listing_template(
    category_external_id: Annotated[UUID, Form()],
    marketplace_external_id: Annotated[UUID, Form()],
    file: UploadFile,
    catalog_session: CatalogSessionDep,
    gcs: GcsDep,
) -> UploadListingTemplateResponse:
    """Store the Amazon listing template for the given category × marketplace in GCS.

    The file is expected to be an ``.xlsx`` spreadsheet (Amazon's flat-file format).
    Uploading again overwrites the previous template for that pair.
    """
    content = file.file.read()
    try:
        return catalog_service.upload_listing_template(
            catalog_session,
            gcs,
            category_external_id=category_external_id,
            marketplace_external_id=marketplace_external_id,
            content=content,
        )
    except CategoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MarketplaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/marketplace-selection", response_model=MarketplaceSelectionResponse)
def get_marketplace_selection(
    _user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
) -> MarketplaceSelectionResponse:
    return catalog_service.get_marketplace_selection(catalog_session)
