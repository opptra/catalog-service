"""Flipkart adapter (not implemented yet)."""

from __future__ import annotations

from listing_mapping.marketplace import MarketplaceId
from utils.listing_template_columns import WorkbookLayout


class FlipkartAdapter:
    @property
    def marketplace_id(self) -> MarketplaceId:
        return MarketplaceId.FLIPKART

    def workbook_layout(
        self,
        *,
        sheet_name: str | None = None,
        header_label_row: int | None = None,
        machine_key_row: int | None = None,
        data_start_row: int | None = None,
    ) -> WorkbookLayout:
        raise NotImplementedError(
            "FLIPKART listing-mapping adapter is not implemented yet. "
            "Add workbook defaults in config and implement FlipkartAdapter."
        )
