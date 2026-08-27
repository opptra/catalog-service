"""Pick an extract prompt family from the product row. Unknown → generic."""

from __future__ import annotations

import re

CATEGORY_GENERIC = "generic"
CATEGORY_BEDSHEET = "bedsheet"

_PLACEHOLDERS = frozenset(
    {
        "tbd",
        "t.b.d",
        "t.b.d.",
        "to be decided",
        "to be determined",
    }
)

_TYPE_HEADERS = (
    "product type",
    "articletype",
    "item type name",
    "item type",
    "type",
)

_BEDSHEET_VALUE_MARKERS = ("bedsheet", "bed sheet", "flat sheet", "fitted sheet")
_BEDSHEET_HEADER_MARKERS = (
    "bed size",
    "bedsheet",
    "pillow cover",
    "pillowcase",
    "number of pillow",
)


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def is_placeholder(value: str) -> bool:
    """True for empty or TBD-style catalog placeholders the judge must skip."""
    key = _norm(value)
    return not key or key in _PLACEHOLDERS


def product_type_column(headers: list[str]) -> str | None:
    normalized = [(name, _norm(name)) for name in headers]
    for marker in _TYPE_HEADERS:
        for name, key in normalized:
            if key == marker:
                return name
    return None


def detect_category(
    headers: list[str],
    attributes: dict[str, str] | None = None,
) -> str:
    """Bedsheet when the row or headers say so; otherwise generic."""
    attrs = attributes or {}
    type_header = product_type_column(headers) or product_type_column(list(attrs))
    if type_header:
        raw = attrs.get(type_header, "")
        if not is_placeholder(raw):
            key = _norm(raw)
            if any(marker in key for marker in _BEDSHEET_VALUE_MARKERS):
                return CATEGORY_BEDSHEET

    for name in headers:
        key = _norm(name)
        if any(marker in key for marker in _BEDSHEET_HEADER_MARKERS):
            return CATEGORY_BEDSHEET
    return CATEGORY_GENERIC
