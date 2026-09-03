"""CLI: generate listing_template_column INSERT SQL from a marketplace .xlsm.

Uses the marketplace adapter for sheet titles / default offsets.

From repo root (server venv):

  PYTHONPATH=ops:server python -m listing_mapping.generate_columns \\
    --marketplace AMAZON \\
    --xlsm /path/to/CATEGORY.xlsm \\
    --out tmp/sql/002_<category>_listing_columns.sql
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from listing_mapping import _bootstrap  # noqa: F401
from listing_mapping.marketplace import parse_marketplace_id
from listing_mapping.marketplace.registry import get_adapter
from utils.listing_template_columns import write_sql


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsm", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--marketplace",
        required=True,
        help="Marketplace adapter id: AMAZON | FLIPKART | MYNTRA",
    )
    parser.add_argument("--sheet-name", default=None)
    parser.add_argument("--header-label-row", type=int, default=None)
    parser.add_argument("--machine-key-row", type=int, default=None)
    parser.add_argument("--data-start-row", type=int, default=None)
    args = parser.parse_args(argv)
    if not args.xlsm.is_file():
        print(f"xlsm not found: {args.xlsm}", file=sys.stderr)
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
    except (ValueError, FileNotFoundError, OSError, NotImplementedError) as exc:
        print(f"generate_columns failed: {exc}", file=sys.stderr)
        return 1

    columns = write_sql(args.xlsm, args.out, layout=layout)
    stages = sorted({c["resolve_stage"] for c in columns})
    enums = sum(1 for c in columns if c["config"]["fill_type"] == "ENUM")
    always = sum(1 for c in columns if c["config"].get("requiredness") == "ALWAYS")
    deps = sum(1 for c in columns if c["config"].get("depends_on"))
    print(
        f"Wrote {args.out} ({len(columns)} columns, {enums} ENUM, "
        f"{always} ALWAYS, {deps} with depends_on, stages={stages}, "
        f"marketplace={marketplace_id.value!r})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
