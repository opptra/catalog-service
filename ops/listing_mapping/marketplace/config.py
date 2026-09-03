"""Load marketplace workbook defaults from config JSON."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from listing_mapping.marketplace import MarketplaceId
from pydantic import BaseModel, ConfigDict, Field

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "marketplace_listing_workbooks.json"
)


class MarketplaceWorkbookConfig(BaseModel):
    """Default blank-workbook layout for one marketplace."""

    model_config = ConfigDict(extra="forbid")

    sheet_name: str
    header_label_row: int = Field(ge=1)
    machine_key_row: int = Field(ge=1)
    data_start_row: int = Field(ge=1)
    valid_values_sheet: str | None = None
    dropdown_lists_sheet: str | None = None
    data_definitions_sheet: str | None = None


@lru_cache(maxsize=1)
def _load_raw() -> dict[str, dict]:
    if not _CONFIG_PATH.is_file():
        raise FileNotFoundError(f"Missing marketplace workbook config: {_CONFIG_PATH}")
    raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(f"{_CONFIG_PATH} must be a JSON object keyed by marketplace id")
    return raw


def config_for(marketplace_id: MarketplaceId) -> MarketplaceWorkbookConfig:
    raw = _load_raw()
    entry = raw.get(marketplace_id.value)
    if entry is None:
        known = ", ".join(sorted(raw.keys())) or "(none)"
        raise ValueError(
            f"No workbook config for {marketplace_id.value}. Known keys: {known}. "
            f"Edit {_CONFIG_PATH}."
        )
    return MarketplaceWorkbookConfig.model_validate(entry)


def clear_config_cache() -> None:
    _load_raw.cache_clear()
