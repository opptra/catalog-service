"""Heuristic column roles.

Maps CSV headers onto visual / long-text / skip groups for extract and the judge.
Extract prompt family comes from ``detect_category`` (generic unless a bedsheet row).
"""

import re

from pipelines.inbound_qc.category import CATEGORY_BEDSHEET, detect_category
from pipelines.inbound_qc.types import Checklist

_LONG_TEXT_MARKERS = (
    "description",
    "title",
    "highlight",
    "product name",
)

_SKIP_MARKERS = (
    "hsn",
    "ean",
    "gtin",
    "barcode",
    "manufacturer",
    "packer",
    "address",
    "pincode",
    "tax",
    "sku",
    "group id",
    "stylegroup",
    "mrp",
    "vendor",
    "product id type",
    "country",
    "category",
    "sub-category",
    "brand name",
)

_CHECKLIST_VISUAL = ("color", "pattern", "size", "item_count", "material")


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def is_long_text_column(name: str) -> bool:
    key = _norm(name)
    return any(marker in key for marker in _LONG_TEXT_MARKERS)


def is_skip_column(name: str) -> bool:
    key = _norm(name)
    return any(marker in key for marker in _SKIP_MARKERS)


def long_text_columns(headers: list[str]) -> list[str]:
    return [name for name in headers if is_long_text_column(name)]


def column_for_visual_field(headers: list[str], visual: str) -> str | None:
    """Best CSV header for a checklist visual name."""
    markers = {
        "color": ("color", "colour"),
        "pattern": ("pattern",),
        "size": ("size", "bed size", "dimension"),
        "item_count": ("number of items", "items included"),
        "material": ("material",),
        "product_type": ("product type", "articletype", "item type name", "item type"),
    }
    wanted = markers.get(visual, ())
    normalized = [(name, _norm(name)) for name in headers]
    for marker in wanted:
        for name, key in normalized:
            if is_skip_column(name) or is_long_text_column(name):
                continue
            if key == marker or key.startswith(f"{marker} "):
                return name
        for name, key in normalized:
            if is_skip_column(name) or is_long_text_column(name):
                continue
            if marker in key:
                return name
    return None


def checklist_from_headers(
    headers: list[str],
    attributes: dict[str, str] | None = None,
) -> Checklist:
    """Visual fields from headers; extract prompt family from the row when given."""
    visual: list[str] = []
    for item in _CHECKLIST_VISUAL:
        if column_for_visual_field(headers, item) is not None:
            visual.append(item)

    category = detect_category(headers, attributes)
    if category == CATEGORY_BEDSHEET and "product_type" not in visual:
        visual.insert(0, "product_type")

    skip = [name for name in headers if is_skip_column(name)]
    return Checklist(visual=tuple(visual), skip=tuple(skip), category=category)
