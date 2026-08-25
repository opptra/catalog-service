"""Catalog UI orchestration — composes category, marketplace, and attribute services."""

from collections import OrderedDict
from uuid import UUID

from sqlalchemy.orm import Session

from core.clients.gcs import GcsClient
from core.exceptions import CategoryNotFoundError, MarketplaceNotFoundError
from dto.listing_config import ListingTemplateMetadata
from dto.response.catalog import (
    MarketplaceSelectionAttributeItemResponse,
    MarketplaceSelectionAttributeResponse,
    MarketplaceSelectionMarketplaceResponse,
    MarketplaceSelectionResponse,
    UploadListingTemplateResponse,
)
from dto.response.category import (
    CategoryTemplateResponse,
    ImportCategoryPathResponse,
    LeafCategoryPageResponse,
)
from entities.catalog.category_marketplace import CategoryMarketplace
from entities.catalog.listing_template import ListingTemplate
from repositories.catalog import category as category_repo
from repositories.catalog import category_marketplace as category_marketplace_repo
from repositories.catalog import listing_template as listing_template_repo
from repositories.catalog import marketplace as marketplace_repo
from services import attribute as attribute_service
from services import category as category_service
from services import marketplace_attribute as marketplace_attribute_service
from services.category import DEFAULT_LEAF_PAGE_SIZE
from utils import flatfile as flatfile_utils

__all__ = ["DEFAULT_LEAF_PAGE_SIZE"]

_LISTING_TEMPLATE_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_DEFAULT_LISTING_METADATA = ListingTemplateMetadata(
    filename="listing-template.xlsx",
    sheet_name="Template",
    header_label_row=4,
    machine_key_row=5,
    data_start_row=7,
)


def list_leaf_categories(
    session: Session,
    *,
    offset: int = 0,
    limit: int = DEFAULT_LEAF_PAGE_SIZE,
) -> LeafCategoryPageResponse:
    return category_service.list_leaf_categories(session, offset=offset, limit=limit)


def get_category_template(session: Session, external_id: UUID) -> CategoryTemplateResponse:
    return category_service.get_category_template(session, external_id)


def import_category_path(session: Session, names: list[str]) -> ImportCategoryPathResponse:
    return category_service.import_category_path(session, names)


def upload_listing_template(
    session: Session,
    gcs: GcsClient,
    *,
    category_external_id: UUID,
    marketplace_external_id: UUID,
    content: bytes,
) -> UploadListingTemplateResponse:
    """Store the Amazon listing template for a category × marketplace pair in GCS
    and upsert the matching ``listing_template`` row (creates ``category_marketplace``
    if missing). Raises ``CategoryNotFoundError`` or ``MarketplaceNotFoundError`` when
    either entity does not exist.
    """
    category = category_repo.get_by_external_id(session, category_external_id)
    if category is None:
        raise CategoryNotFoundError(f"Category {category_external_id} not found")

    marketplace = marketplace_repo.get_by_external_id(session, marketplace_external_id)
    if marketplace is None:
        raise MarketplaceNotFoundError(f"Marketplace {marketplace_external_id} not found")

    object_key = flatfile_utils.listing_template_object_key(
        marketplace_external_id, category_external_id
    )
    gcs.upload_bytes(content, object_key, content_type=_LISTING_TEMPLATE_CONTENT_TYPE)

    junction = category_marketplace_repo.get_by_marketplace_and_category(
        session, marketplace.id, category.id
    )
    if junction is None:
        junction = category_marketplace_repo.save(
            session,
            CategoryMarketplace(
                marketplace_id=marketplace.id,
                category_id=category.id,
            ),
        )

    existing = listing_template_repo.get_by_category_marketplace_id(session, junction.id)
    metadata = dict(_DEFAULT_LISTING_METADATA.model_dump())
    if existing is None:
        listing_template_repo.save(
            session,
            ListingTemplate(
                category_marketplace_id=junction.id,
                gcs_object_key=object_key,
                metadata_=metadata,
            ),
        )
    else:
        existing.gcs_object_key = object_key
        if not existing.metadata_:
            existing.metadata_ = metadata
        listing_template_repo.save(session, existing)

    return UploadListingTemplateResponse(
        category_external_id=category_external_id,
        marketplace_external_id=marketplace_external_id,
        gcs_object_key=object_key,
    )


def get_marketplace_selection(session: Session) -> MarketplaceSelectionResponse:
    """Return marketplaces that have attribute mappings, each with its own attribute groups.

    Marketplaces with no ``marketplace_attribute`` rows are omitted (not selectable yet).
    """
    marketplaces = list(marketplace_repo.list_all(session))
    rules_by_marketplace = marketplace_attribute_service.list_rules_by_marketplace_ids(
        session, [row.id for row in marketplaces]
    )

    items: list[MarketplaceSelectionMarketplaceResponse] = []
    for marketplace in marketplaces:
        rules = rules_by_marketplace.get(marketplace.id, [])
        if not rules:
            continue

        grouped: OrderedDict[str, list[marketplace_attribute_service.MarketplaceAttributeRules]] = (
            OrderedDict()
        )
        for rule in rules:
            key = (
                rule.master.group_label.value
                if rule.master.group_label is not None
                else rule.master.name.value
            )
            grouped.setdefault(key, []).append(rule)

        items.append(
            MarketplaceSelectionMarketplaceResponse(
                external_id=marketplace.external_id,
                name=marketplace.name,
                attributes=[
                    MarketplaceSelectionAttributeResponse(
                        id=label,
                        label=attribute_service.display_label(label),
                        items=[
                            MarketplaceSelectionAttributeItemResponse(
                                external_id=rule.master.external_id,
                                name=rule.master.name.value,
                                allows_quantity=rule.master.allows_quantity,
                                quantity=rule.image_quantity
                                if rule.image_quantity is not None
                                else 1,
                                config=rule.config,
                            )
                            for rule in group_rules
                        ],
                    )
                    for label, group_rules in grouped.items()
                ],
            )
        )

    return MarketplaceSelectionResponse(marketplaces=items)
