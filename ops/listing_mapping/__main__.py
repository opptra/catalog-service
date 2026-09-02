"""Offline CLI: mapping CSV + marketplace .xlsm → human-run listing SQL.

Valid Values / Dropdown Lists sheet names come from
``ops/listing_mapping/config/marketplace_listing_workbooks.json`` keyed by the
CSV marketplace column header (e.g. Amazon) — not from CLI flags.

From repo root (server venv):

  PYTHONPATH=ops:server python -m listing_mapping \\
    --xlsm /path/to/CATEGORY.xlsm \\
    --csv /path/to/mapping.csv \\
    --sheet-name Template \\
    --header-label-row 4 \\
    --machine-key-row 5 \\
    --data-start-row 7 \\
    --out tmp/sql/003_<category>_listing_mapping.sql
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from listing_mapping import _bootstrap  # noqa: F401
from listing_mapping.csv import parse_mapping_csv
from listing_mapping.marketplace_workbook import sheets_for_marketplace
from listing_mapping.overlay import overlay_columns
from listing_mapping.render import render_mapping_sql

from utils.listing_template_columns import WorkbookLayout, build_columns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsm", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sheet-name", required=True)
    parser.add_argument("--header-label-row", type=int, required=True)
    parser.add_argument("--machine-key-row", type=int, required=True)
    parser.add_argument("--data-start-row", type=int, required=True)
    args = parser.parse_args(argv)

    if not args.xlsm.is_file():
        print(f"xlsm not found: {args.xlsm}", file=sys.stderr)
        return 1
    if not args.csv.is_file():
        print(f"csv not found: {args.csv}", file=sys.stderr)
        return 1
    for name, value in (
        ("--header-label-row", args.header_label_row),
        ("--machine-key-row", args.machine_key_row),
        ("--data-start-row", args.data_start_row),
    ):
        if value < 1:
            print(f"{name} must be >= 1, got {value}", file=sys.stderr)
            return 1

    try:
        mapping = parse_mapping_csv(args.csv)
        sheets = sheets_for_marketplace(mapping.marketplace_header)
        layout = WorkbookLayout(
            sheet_name=args.sheet_name,
            header_label_row=args.header_label_row,
            machine_key_row=args.machine_key_row,
            data_start_row=args.data_start_row,
            valid_values_sheet=sheets.valid_values_sheet,
            dropdown_lists_sheet=sheets.dropdown_lists_sheet,
            data_definitions_sheet=sheets.data_definitions_sheet,
        )
        workbook_columns = build_columns(
            args.xlsm,
            layout=layout,
            include_requiredness=False,
        )
        result = overlay_columns(workbook_columns, mapping)
        sql = render_mapping_sql(
            columns=result.columns,
            attribute_spec=result.attribute_spec,
            layout=layout,
            xlsm_name=args.xlsm.name,
            csv_name=args.csv.name,
            marketplace_header=mapping.marketplace_header,
            warnings=result.warnings,
        )
    except (ValueError, OSError) as exc:
        print(f"listing_mapping failed: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(sql, encoding="utf-8")

    by_fill: dict[str, int] = {}
    for col in result.columns:
        fill = col["config"]["fill_type"]
        by_fill[fill] = by_fill.get(fill, 0) + 1
    print(
        f"Wrote {args.out} ({len(result.columns)} columns, fill_types={by_fill}, "
        f"marketplace={mapping.marketplace_header!r}, "
        f"valid_values_sheet={layout.valid_values_sheet!r}, "
        f"allowed={len(result.attribute_spec['allowed'])}, "
        f"mandatory={len(result.attribute_spec['mandatory'])}, "
        f"warnings={len(result.warnings)})",
        file=sys.stderr,
    )
    for warning in result.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
