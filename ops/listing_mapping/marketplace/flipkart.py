"""Flipkart blank listing-workbook adapter."""

from __future__ import annotations

from listing_mapping.marketplace import MarketplaceId
from listing_mapping.marketplace.config import workbook_layout_for
from utils.listing_template_columns import WorkbookLayout


class FlipkartAdapter:
    """Flipkart category sheet: labels row 1, type hints row 2, data from row 5.

    Blank must be ``.xlsx`` or ``.xlsm`` (Excel Save As from ``.xls``). Keep
    ``.xlsm`` when the file has a VB project. Default ``sheet_name`` is
    category-specific (e.g. ``bedsheet``). Pass ``--sheet-name`` when the
    blank workbook uses a different listing sheet. Variant sheets
    (``Parent Variant Products``) are not used.
    """

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
        return workbook_layout_for(
            MarketplaceId.FLIPKART,
            sheet_name=sheet_name,
            header_label_row=header_label_row,
            machine_key_row=machine_key_row,
            data_start_row=data_start_row,
        )
