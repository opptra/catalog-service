"""Catalog UI orchestration — composes category, marketplace, and attribute services."""

from uuid import UUID

from sqlalchemy.orm import Session

from dto.response.catalog import (
    MarketplaceSelectionAttributeItemResponse,
    MarketplaceSelectionAttributeResponse,
    MarketplaceSelectionResponse,
)
from dto.response.category import CategoryTemplateResponse, LeafCategoryPageResponse
from services import attribute as attribute_service
from services import category as category_service
from services import marketplace as marketplace_service
from services.category import DEFAULT_LEAF_PAGE_SIZE

__all__ = ["DEFAULT_LEAF_PAGE_SIZE"]


def list_leaf_categories(
    session: Session,
    *,
    offset: int = 0,
    limit: int = DEFAULT_LEAF_PAGE_SIZE,
) -> LeafCategoryPageResponse:
    return category_service.list_leaf_categories(session, offset=offset, limit=limit)


def get_category_template(session: Session, external_id: UUID) -> CategoryTemplateResponse:
    return category_service.get_category_template(session, external_id)


def get_marketplace_selection(session: Session) -> MarketplaceSelectionResponse:
    """Return available marketplaces and attribute groups for the marketplace selection step."""
    marketplaces = marketplace_service.list_marketplaces(session).items
    groups = attribute_service.list_attribute_groups(session).items
    return MarketplaceSelectionResponse(
        marketplaces=marketplaces,
        attributes=[
            MarketplaceSelectionAttributeResponse(
                id=group.label,
                label=attribute_service.display_label(group.label),
                items=[
                    MarketplaceSelectionAttributeItemResponse(
                        external_id=item.external_id,
                        allows_quantity=item.allows_quantity,
                    )
                    for item in group.attributes
                ],
            )
            for group in groups
        ],
    )
