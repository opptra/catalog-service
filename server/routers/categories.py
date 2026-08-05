from typing import Annotated
from uuid import UUID

from fastapi import HTTPException, Query

from core.auth import SecureAPIRouter
from core.deps import CatalogSessionDep, CurrentUserDep
from core.exceptions import CategoryNotFoundError
from dto.response.category import CategoryTemplateResponse, LeafCategoryPageResponse
from services import category as category_service
from services.category import DEFAULT_LEAF_PAGE_SIZE

router = SecureAPIRouter(prefix="/categories", tags=["categories"])


@router.get("/leaves", response_model=LeafCategoryPageResponse)
def list_leaf_categories(
    _user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=DEFAULT_LEAF_PAGE_SIZE)] = DEFAULT_LEAF_PAGE_SIZE,
) -> LeafCategoryPageResponse:
    return category_service.list_leaf_categories(
        catalog_session,
        offset=offset,
        limit=limit,
    )


@router.get("/{external_id}/template", response_model=CategoryTemplateResponse)
def get_category_template(
    external_id: UUID,
    _user: CurrentUserDep,
    catalog_session: CatalogSessionDep,
) -> CategoryTemplateResponse:
    try:
        return category_service.get_category_template(catalog_session, external_id)
    except CategoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
