"""Seed a mapping workbook from a blank marketplace .xlsm.

Fills ``marketplace_columns`` from the workbook and applies a starter
``listing_map`` for Amazon BED_LINEN_SET-style layouts (safe fill_modes that
respect dropdown vs free-text columns).

From repo root (server venv):

  PYTHONPATH=ops:server python -m listing_mapping.seed_from_xlsm \\
    --marketplace AMAZON \\
    --xlsm \"$HOME/Downloads/Marketplace Template/BED_LINEN_SET (1).xlsm\" \\
    --out tmp/listing_mapping_bed_linen_set.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from listing_mapping import _bootstrap  # noqa: F401
from listing_mapping.build_template import build
from listing_mapping.marketplace import parse_marketplace_id
from listing_mapping.marketplace.registry import get_adapter
from utils.listing_template_columns import build_columns


def _is_dropdown(config: dict) -> bool:
    if config.get("fill_type") == "ENUM":
        return True
    return bool(config.get("valid_values") or config.get("valid_values_by_parent"))


def _label_key(label: str) -> str:
    return " ".join(label.casefold().split())


def _bed_linen_map_rows(
    by_index: dict[int, dict],
) -> list[tuple[int, str, str, str, str]]:
    """Starter mapping for Amazon BED_LINEN_SET column layout."""
    rows: list[tuple[int, str, str, str, str]] = []

    def add(
        idx: int,
        mode: str,
        *,
        pim: str = "",
        gen: str = "",
        const: str = "",
    ) -> None:
        if idx not in by_index:
            raise ValueError(f"Expected column_index={idx} in workbook")
        rows.append((idx, mode, pim, gen, const))

    add(1, "COPY_PIM", pim="SKU")
    # Product Type has a single allowed value in this workbook.
    add(2, "CONSTANT", const="BED_LINEN_SET")
    add(3, "CONSTANT", const="Edit (Partial Update)")
    add(4, "ENUM_AI")  # Parentage Level (dropdown)
    add(5, "SKIP")  # Parent SKU — free text, not ENUM
    add(6, "ENUM_AI")  # Variation Theme Name
    add(7, "COPY_GENERATION", gen="TITLE")
    add(8, "COPY_GENERATION", gen="ITEM_HIGHLIGHTS:1")
    add(9, "ENUM_FROM_PIM", pim="Brand")
    add(10, "SKIP")  # Product Id Type
    add(11, "SKIP")  # Product Id

    add(21, "IMAGE", gen="IMAGE:1")
    for slot, idx in enumerate(range(22, 30), start=2):
        add(idx, "IMAGE", gen=f"IMAGE:{slot}")

    add(31, "COPY_GENERATION", gen="DESCRIPTION")
    for n, idx in enumerate(range(32, 37), start=1):
        add(idx, "COPY_GENERATION", gen=f"BULLET_POINTS:{n}")
    add(37, "COPY_GENERATION", gen="BACKEND_KEYWORDS")

    add(39, "ENUM_FROM_PIM", pim="Material")  # first Material slot
    add(51, "ENUM_FROM_PIM", pim="Color")
    add(52, "ENUM_FROM_PIM", pim="Size")
    add(78, "ENUM_FROM_PIM", pim="Pattern")

    # Sanity: ENUM_* only on dropdown columns; IMAGE/COPY_GENERATION not on enums.
    for idx, mode, _pim, _gen, _const in rows:
        cfg = by_index[idx]
        dd = _is_dropdown(cfg)
        label = cfg.get("label")
        if mode in {"ENUM_AI", "ENUM_FROM_PIM"} and not dd:
            raise ValueError(
                f"column_index={idx} ({label!r}): {mode} requires a dropdown"
            )
        if mode in {"COPY_GENERATION", "AI_TEXT", "IMAGE"} and dd:
            raise ValueError(
                f"column_index={idx} ({label!r}): {mode} is free-text but column "
                "is a dropdown — use ENUM_AI / ENUM_FROM_PIM"
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--marketplace", required=True)
    parser.add_argument("--xlsm", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sheet-name", default=None)
    parser.add_argument("--header-label-row", type=int, default=None)
    parser.add_argument("--machine-key-row", type=int, default=None)
    parser.add_argument("--data-start-row", type=int, default=None)
    args = parser.parse_args(argv)

    if not args.xlsm.is_file():
        print(f"xlsm not found: {args.xlsm}", file=sys.stderr)
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
        columns = build_columns(args.xlsm, layout=layout, include_requiredness=False)
    except (ValueError, FileNotFoundError, OSError, NotImplementedError) as exc:
        print(f"seed_from_xlsm failed: {exc}", file=sys.stderr)
        return 1

    by_index = {int(c["column_index"]): c["config"] for c in columns}
    mkt_rows = [
        (int(c["column_index"]), str(c["config"].get("label") or "")) for c in columns
    ]

    if (
        marketplace_id.value == "AMAZON"
        and _label_key(by_index.get(2, {}).get("label", "")) == "product type"
    ):
        map_rows = _bed_linen_map_rows(by_index)
    else:
        print(
            "No starter listing_map for this workbook shape; "
            "wrote marketplace_columns only (empty listing_map not allowed).",
            file=sys.stderr,
        )
        return 1

    pim_rows = [
        ("SKU", "Mandatory"),
        ("Color", "Mandatory"),
        ("Size", "Mandatory"),
        ("Material", "Optional"),
        ("Brand", "Mandatory"),
        ("Pattern", "Optional"),
    ]

    out = build(
        out_xlsx=args.out,
        out_dir=args.out.with_suffix("").parent / (args.out.stem + "_sheets"),
        out_readme=args.out.with_name(args.out.stem + "_README.txt"),
        pim_rows=pim_rows,
        mkt_rows=mkt_rows,
        map_rows=map_rows,
        write_sidecar_csv=True,
    )
    print(
        f"Wrote {out} ({len(mkt_rows)} marketplace columns, "
        f"{len(map_rows)} listing_map rows; unmapped columns → SKIP at overlay)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
