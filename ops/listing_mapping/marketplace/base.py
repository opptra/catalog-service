"""Marketplace adapter contract for blank listing-workbook parsing."""

from __future__ import annotations

from typing import Protocol

from listing_mapping.marketplace import MarketplaceId

from utils.listing_template_columns import WorkbookLayout


class MarketplaceAdapter(Protocol):
    """Per-marketplace rules for blank .xlsm layout and sheet titles.

    Parent/child ENUM discovery stays in the shared workbook parser; adapters
    supply offsets and optional sheet names that differ by marketplace.
    """

    @property
    def marketplace_id(self) -> MarketplaceId: ...

    def workbook_layout(
        self,
        *,
        sheet_name: str | None = None,
        header_label_row: int | None = None,
        machine_key_row: int | None = None,
        data_start_row: int | None = None,
    ) -> WorkbookLayout:
        """Return parse layout; CLI may override individual offsets."""
        ...
