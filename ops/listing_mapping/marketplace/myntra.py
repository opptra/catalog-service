"""Myntra blank listing-workbook adapter."""

from __future__ import annotations

from listing_mapping.marketplace import MarketplaceId
from listing_mapping.marketplace.config import workbook_layout_for
from utils.listing_template_columns import WorkbookLayout


class MyntraAdapter:
    """Myntra category sheet: labels on row 3, data from row 4.

    Default ``sheet_name`` is category-specific (e.g. ``Bedsheets``). Pass
    ``--myntra-sheet-name`` / ``--sheet-name`` when the blank workbook uses a
    different listing sheet.
    """

    @property
    def marketplace_id(self) -> MarketplaceId:
        return MarketplaceId.MYNTRA

    def workbook_layout(
        self,
        *,
        sheet_name: str | None = None,
        header_label_row: int | None = None,
        machine_key_row: int | None = None,
        data_start_row: int | None = None,
    ) -> WorkbookLayout:
        return workbook_layout_for(
            MarketplaceId.MYNTRA,
            sheet_name=sheet_name,
            header_label_row=header_label_row,
            machine_key_row=machine_key_row,
            data_start_row=data_start_row,
        )
