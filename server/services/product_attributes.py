"""Read SKU product attributes through the category allowed list.

Call ``for_skus`` whenever PIM facts are needed. Unique categories are loaded
once, allowed names are resolved once per category, then each SKU is mapped.
Extra keys on ``sku_master.attributes`` must not reach generation, listing fill,
or verification.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from core.exceptions import CategoryNotFoundError
from entities.catalog.sku_master import SkuMaster
from repositories.catalog import category as category_repository
from services import category as category_service

_IDENTITY_KEY = "SKU"


def filter_allowed(
    attributes: dict[str, Any] | None,
    allowed_names: frozenset[str],
) -> dict[str, Any]:
    """Keep only keys the category allows. ``SKU`` is always kept as identity."""
    keep = allowed_names | {_IDENTITY_KEY}
    return {key: value for key, value in dict(attributes or {}).items() if key in keep}


def for_skus(session: Session, skus: Sequence[SkuMaster]) -> dict[int, dict[str, Any]]:
    """Filter attributes for many SKUs without a per-SKU category round-trip.

    Unique ``category_id``s are loaded in one query. Attribute-master names for
    those specs are loaded in one query. Returns ``sku.id →`` allowed attributes.
    """
    if not skus:
        return {}

    category_ids = list({sku.category_id for sku in skus})
    categories = list(category_repository.list_by_ids(session, category_ids))
    found_ids = {category.id for category in categories}
    missing = sorted(cid for cid in category_ids if cid not in found_ids)
    if missing:
        raise CategoryNotFoundError(
            f"Category not found: {missing[0]}"
            if len(missing) == 1
            else f"Categories not found: {missing}"
        )

    allowed_by_category = category_service.allowed_product_attribute_names_for_categories(
        session, categories
    )
    return {
        sku.id: filter_allowed(sku.attributes, allowed_by_category[sku.category_id]) for sku in skus
    }
