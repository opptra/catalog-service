"""Amazon blank listing-workbook adapter."""

from __future__ import annotations

from listing_mapping.marketplace import MarketplaceId
from listing_mapping.marketplace.config import workbook_layout_for
from utils.listing_template_columns import WorkbookLayout


class AmazonAdapter:
    """Amazon Template sheet: labels row 4, machine keys row 5, data from row 7."""

    @property
    def marketplace_id(self) -> MarketplaceId:
        return MarketplaceId.AMAZON

    def workbook_layout(
        self,
        *,
        sheet_name: str | None = None,
        header_label_row: int | None = None,
        machine_key_row: int | None = None,
        data_start_row: int | None = None,
    ) -> WorkbookLayout:
        return workbook_layout_for(
            MarketplaceId.AMAZON,
            sheet_name=sheet_name,
            header_label_row=header_label_row,
            machine_key_row=machine_key_row,
            data_start_row=data_start_row,
        )
