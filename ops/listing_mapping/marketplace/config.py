"""Load marketplace workbook defaults from the server-side JSON (one source)."""

from __future__ import annotations

from listing_mapping.marketplace import MarketplaceId
from utils.listing_marketplace import (
    MarketplaceWorkbookConfig,
    clear_config_cache,
    config_for_key,
    workbook_layout_for_key,
)
from utils.listing_template_columns import WorkbookLayout

__all__ = [
    "MarketplaceWorkbookConfig",
    "clear_config_cache",
    "config_for",
    "workbook_layout_for",
]


def config_for(marketplace_id: MarketplaceId) -> MarketplaceWorkbookConfig:
    return config_for_key(marketplace_id.value)


def workbook_layout_for(
    marketplace_id: MarketplaceId,
    *,
    sheet_name: str | None = None,
    header_label_row: int | None = None,
    machine_key_row: int | None = None,
    data_start_row: int | None = None,
) -> WorkbookLayout:
    return workbook_layout_for_key(
        marketplace_id.value,
        sheet_name=sheet_name,
        header_label_row=header_label_row,
        machine_key_row=machine_key_row,
        data_start_row=data_start_row,
    )
