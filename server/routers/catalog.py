"""Shared catalog UI data — categories and batch generation options."""

from typing import Annotated
from uuid import UUID

from fastapi import HTTPException, Query

from core.auth import SecureAPIRouter
from core.deps import CatalogSessionDep, CurrentUserDep
from core.exceptions import CategoryNotFoundError
from dto.response.catalog import MarketplaceSelectionResponse
from dto.response.category import CategoryTemplateResponse, LeafCategoryPageResponse
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


@router.get("/marketplace-selection", response_model=MarketplaceSelectionResponse)
def get_marketplace_selection(
    _user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
) -> MarketplaceSelectionResponse:
    return catalog_service.get_marketplace_selection(catalog_session)
