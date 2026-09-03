"""Offline CLI: mapping workbook + marketplace .xlsm → human-run listing SQL.

Uses the restricted Excel mapping template (pim_contract + listing_map) and a
marketplace adapter (AMAZON implemented; FLIPKART/MYNTRA stubs).

From repo root (server venv):

  PYTHONPATH=ops:server python -m listing_mapping \\
    --marketplace AMAZON \\
    --xlsm /path/to/CATEGORY.xlsm \\
    --mapping tmp/listing_mapping_template.xlsx \\
    --out tmp/sql/003_<category>_listing_mapping.sql

Optional layout overrides (when a blank workbook differs from marketplace defaults):
  --sheet-name --header-label-row --machine-key-row --data-start-row
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from listing_mapping import _bootstrap  # noqa: F401
from listing_mapping.mapping_workbook import parse_mapping_workbook
from listing_mapping.marketplace import parse_marketplace_id
from listing_mapping.marketplace.registry import get_adapter
from listing_mapping.overlay import overlay_columns
from listing_mapping.render import render_mapping_sql

from utils.listing_template_columns import build_columns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--marketplace",
        required=True,
        help="Marketplace adapter id: AMAZON | FLIPKART | MYNTRA",
    )
    parser.add_argument("--xlsm", type=Path, required=True)
    parser.add_argument(
        "--mapping",
        type=Path,
        required=True,
        help="Listing mapping Excel workbook (pim_contract + listing_map)",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sheet-name", default=None)
    parser.add_argument("--header-label-row", type=int, default=None)
    parser.add_argument("--machine-key-row", type=int, default=None)
    parser.add_argument("--data-start-row", type=int, default=None)
    args = parser.parse_args(argv)

    if not args.xlsm.is_file():
        print(f"xlsm not found: {args.xlsm}", file=sys.stderr)
        return 1
    if not args.mapping.is_file():
        print(f"mapping workbook not found: {args.mapping}", file=sys.stderr)
        return 1
    for name, value in (
        ("--header-label-row", args.header_label_row),
        ("--machine-key-row", args.machine_key_row),
        ("--data-start-row", args.data_start_row),
    ):
        if value is not None and value < 1:
            print(f"{name} must be >= 1, got {value}", file=sys.stderr)
            return 1

    try:
        marketplace_id = parse_marketplace_id(args.marketplace)
        adapter = get_adapter(marketplace_id)
        layout = adapter.workbook_layout(
            sheet_name=args.sheet_name,
            header_label_row=args.header_label_row,
            machine_key_row=args.machine_key_row,
            data_start_row=args.data_start_row,
        )
        mapping = parse_mapping_workbook(args.mapping)
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
            mapping_name=args.mapping.name,
            marketplace_id=marketplace_id.value,
            warnings=result.warnings,
        )
    except (ValueError, OSError, FileNotFoundError, NotImplementedError) as exc:
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
        f"marketplace={marketplace_id.value}, "
        f"sheet={layout.sheet_name!r}, data_start_row={layout.data_start_row}, "
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
