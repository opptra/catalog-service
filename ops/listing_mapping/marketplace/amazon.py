"""Amazon blank listing-workbook adapter."""

from __future__ import annotations

from listing_mapping.marketplace import MarketplaceId
from listing_mapping.marketplace.config import config_for
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
        cfg = config_for(MarketplaceId.AMAZON)
        return WorkbookLayout(
            sheet_name=cfg.sheet_name if sheet_name is None else sheet_name,
            header_label_row=(
                cfg.header_label_row if header_label_row is None else header_label_row
            ),
            machine_key_row=cfg.machine_key_row
            if machine_key_row is None
            else machine_key_row,
            data_start_row=cfg.data_start_row
            if data_start_row is None
            else data_start_row,
            valid_values_sheet=cfg.valid_values_sheet,
            dropdown_lists_sheet=cfg.dropdown_lists_sheet,
            data_definitions_sheet=cfg.data_definitions_sheet,
        )
