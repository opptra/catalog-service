"""The only door to ``sku_master.attributes``.

Read product facts with ``for_sku`` / ``for_skus`` / ``facts_for_sku`` /
``present_for_sku``. Persist with ``apply_write``. Identity helpers
(``business_sku_id``, ``display_name``) live here too.

Services, pipelines, and routers must not read or assign ``sku.attributes``.
The ORM column stays on the entity for repositories (JSONB path queries) and
for this module. ``tests/test_product_attributes_gate.py`` fails the PR if
that is bypassed.
"""

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from core.exceptions import CategoryNotFoundError
from entities.catalog.sku_master import SkuMaster
from repositories.catalog import category as category_repository
from services import category as category_service

_IDENTITY_KEY = "SKU"
_DISPLAY_NAME_KEYS = ("title", "name", "product_name")


def for_sku(session: Session, sku: SkuMaster) -> dict[str, Any]:
    """Category-allowed attributes for one SKU (empty cells kept)."""
    return for_skus(session, [sku]).get(sku.id, {})


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
        sku.id: _filter_allowed(sku.attributes, allowed_by_category[sku.category_id])
        for sku in skus
    }


def facts_for_sku(session: Session, sku: SkuMaster) -> dict[str, Any]:
    """Allowed attributes that have a value — generation PRODUCT DATA."""
    return {key: value for key, value in for_sku(session, sku).items() if not _is_blank(value)}


def present_for_sku(session: Session, sku: SkuMaster) -> list[dict[str, str]]:
    """Filled allowed attributes as name/value pairs for inspection UIs."""
    return [
        {"name": key, "value": _display_value(value)}
        for key, value in facts_for_sku(session, sku).items()
    ]


def prepare_write(
    attributes: dict[str, Any] | None,
    allowed_names: frozenset[str],
) -> dict[str, Any]:
    """Keep only keys the category allows. ``SKU`` is always kept as identity."""
    return _filter_allowed(attributes, allowed_names)


def apply_write(
    sku: SkuMaster,
    attributes: dict[str, Any] | None,
    allowed_names: frozenset[str],
) -> None:
    """Assign the JSONB column after the allowed-list filter."""
    sku.attributes = _filter_allowed(attributes, allowed_names)


def merge_base(sku: SkuMaster | None) -> dict[str, Any] | None:
    """Stored JSON snapshot for overlay-then-``apply_write``. Not product facts."""
    if sku is None:
        return None
    return dict(sku.attributes or {})


def business_sku_id(sku: SkuMaster | None, *, fallback: str = "") -> str:
    """``attributes.SKU`` identity. Not a PIM dump."""
    if sku is None:
        return fallback
    raw = (sku.attributes or {}).get(_IDENTITY_KEY)
    if raw is None:
        return fallback
    text = str(raw).strip()
    return text if text else fallback


def display_name(sku: SkuMaster | None, business_sku_id_value: str) -> str | None:
    """UI label from common title keys, else the business SKU id."""
    if sku is None:
        return business_sku_id_value or None
    attrs = sku.attributes or {}
    for key in _DISPLAY_NAME_KEYS:
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return business_sku_id_value or None


def _filter_allowed(
    attributes: dict[str, Any] | None,
    allowed_names: frozenset[str],
) -> dict[str, Any]:
    keep = allowed_names | {_IDENTITY_KEY}
    return {key: value for key, value in dict(attributes or {}).items() if key in keep}


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _display_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
