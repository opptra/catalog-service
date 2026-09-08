"""Marketplace adapter contract for blank listing-workbook parsing."""

from __future__ import annotations

from typing import Protocol

from listing_mapping.marketplace import MarketplaceId

from utils.listing_template_columns import WorkbookLayout


class MarketplaceAdapter(Protocol):
    """Per-marketplace rules for blank listing-workbook layout.

    Adapters supply sheet offsets and ``enum_discovery`` so Amazon named
    ranges, Flipkart ``DropDownValuesForColumn*`` / Index sheets, and Myntra
    ``masterdata`` ranges never share one mixed parser path. Fill is the same
    ENUM/DIRECT_MAP engine once columns are stored.
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
