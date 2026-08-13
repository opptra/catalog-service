"""CLI: generate listing_template_column INSERT SQL from an Amazon .xlsm.

From server/:

  python -m utils.generate_listing_columns \\
    --xlsm /path/to/CATEGORY.xlsm \\
    --out ../tmp/sql/002_<category>_listing_columns.sql
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from utils.listing_template_columns import write_sql


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsm", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.xlsm.is_file():
        print(f"xlsm not found: {args.xlsm}", file=sys.stderr)
        return 1

    columns = write_sql(args.xlsm, args.out)
    stages = sorted({c["resolve_stage"] for c in columns})
    enums = sum(1 for c in columns if c["config"]["fill_type"] == "ENUM")
    always = sum(1 for c in columns if c["config"]["requiredness"] == "ALWAYS")
    deps = sum(1 for c in columns if c["config"].get("depends_on"))
    print(
        f"Wrote {args.out} ({len(columns)} columns, {enums} ENUM, "
        f"{always} ALWAYS, {deps} with depends_on, stages={stages})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
