"""Marketplace listing-workbook sheet names for this ops utility.

Stored as JSON keyed by marketplace name (matches the mapping CSV marketplace
column header, e.g. ``Amazon``). Edit
``ops/listing_mapping/config/marketplace_listing_workbooks.json`` when a
marketplace uses different sheet titles — do not hardcode in Python.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "marketplace_listing_workbooks.json"


class MarketplaceListingWorkbookSheets(BaseModel):
    """Optional workbook sheet titles used while parsing a blank listing .xlsm."""

    model_config = ConfigDict(extra="forbid")

    valid_values_sheet: str | None = None
    dropdown_lists_sheet: str | None = None
    data_definitions_sheet: str | None = None


@lru_cache(maxsize=1)
def _load_raw() -> dict[str, dict[str, str | None]]:
    if not _CONFIG_PATH.is_file():
        raise FileNotFoundError(
            f"Marketplace listing workbook config missing: {_CONFIG_PATH}. "
            "Add an entry keyed by marketplace name."
        )
    raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{_CONFIG_PATH} must be a JSON object keyed by marketplace name")
    return raw


def list_marketplace_keys() -> list[str]:
    return sorted(_load_raw().keys(), key=str.casefold)


def sheets_for_marketplace(marketplace: str) -> MarketplaceListingWorkbookSheets:
    """Resolve sheet titles for a marketplace name (case-insensitive)."""
    needle = marketplace.strip()
    if not needle:
        raise ValueError("marketplace name is empty")
    raw = _load_raw()
    by_fold = {str(key).casefold(): (str(key), value) for key, value in raw.items()}
    hit = by_fold.get(needle.casefold())
    if hit is None:
        known = ", ".join(list_marketplace_keys()) or "(none)"
        raise ValueError(
            f"No listing-workbook config for marketplace {marketplace!r}. "
            f"Known keys: {known}. Edit {_CONFIG_PATH}."
        )
    _key, value = hit
    if value is None:
        return MarketplaceListingWorkbookSheets()
    if not isinstance(value, dict):
        raise ValueError(f"Config for marketplace {marketplace!r} must be a JSON object")
    return MarketplaceListingWorkbookSheets.model_validate(value)


def clear_sheets_cache() -> None:
    """Test helper — drop the cached JSON parse."""
    _load_raw.cache_clear()
