"""Offline CLI: mapping workbook + marketplace listing workbook → human-run listing SQL.

Uses the restricted Excel mapping template (pim_contract + amazon_mapping /
flipkart_mapping / myntra_mapping) and a marketplace adapter (AMAZON, FLIPKART,
MYNTRA). One mapping workbook; generate any subset of marketplaces.

The command prompts for the IDs of each marketplace it will generate, then
inlines them as SQL literals (no SQL-client binds). Extra workbooks can stay
on the command line; they are not prompted unless selected.

From repo root (server venv), Amazon only (Flipkart/Myntra files optional):

  PYTHONPATH=ops:server python -m listing_mapping \\
    --mapping ops/docs/listing_mapping_template.xlsx \\
    --amazon-xlsm tmp/listing_mapping/input/BED_LINEN_SET.xlsm \\
    --flipkart-xlsm tmp/listing_mapping/input/bedsheet.xlsm \\
    --myntra-xlsm tmp/listing_mapping/input/myntra.xlsx \\
    --out-dir tmp/listing_mapping/sql \\
    --only AMAZON

All provided marketplaces (Enter skips a marketplace you are not ready for):

  PYTHONPATH=ops:server python -m listing_mapping \\
    --mapping ops/docs/listing_mapping_template.xlsx \\
    --amazon-xlsm tmp/listing_mapping/input/BED_LINEN_SET.xlsm \\
    --flipkart-xlsm tmp/listing_mapping/input/bedsheet.xlsm \\
    --myntra-xlsm tmp/listing_mapping/input/myntra.xlsx \\
    --out-dir tmp/listing_mapping/sql

Single marketplace:

  PYTHONPATH=ops:server python -m listing_mapping \\
    --marketplace AMAZON \\
    --xlsm tmp/listing_mapping/input/BED_LINEN_SET.xlsm \\
    --mapping ops/docs/listing_mapping_template.xlsx \\
    --out tmp/listing_mapping/amazon/sql/003_bed_linen_set_listing_mapping.sql

Optional layout overrides (when a blank workbook differs from marketplace defaults):
  --sheet-name --header-label-row --machine-key-row --data-start-row
  All-at-once sheet overrides: --amazon-sheet-name --flipkart-sheet-name --myntra-sheet-name
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from listing_mapping import _bootstrap  # noqa: F401
from listing_mapping.mapping_workbook import parse_mapping_workbook
from listing_mapping.marketplace import MarketplaceId, parse_marketplace_id
from listing_mapping.marketplace.registry import get_adapter
from listing_mapping.overlay import overlay_columns
from listing_mapping.render import ApplyIds, render_mapping_sql
from utils.listing_template_columns import build_columns


@dataclass(frozen=True)
class MappingJob:
    marketplace_id: MarketplaceId
    xlsm: Path
    out: Path
    sheet_name: str | None = None
    header_label_row: int | None = None
    machine_key_row: int | None = None
    data_start_row: int | None = None


def _positive_int(name: str, value: int | None) -> None:
    if value is not None and value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}")


def _parse_only(raw: str | None) -> frozenset[MarketplaceId] | None:
    if raw is None or not str(raw).strip():
        return None
    return frozenset(parse_marketplace_id(part) for part in str(raw).split(",") if part.strip())


def _parse_uuid(label: str, raw: str) -> str:
    text = raw.strip()
    try:
        return str(uuid.UUID(text))
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID, got {raw!r}") from exc


def _stdin_prompt(label: str) -> str:
    if not sys.stdin.isatty():
        raise ValueError(f"Missing {label}. Pass the CLI flags, use --only, or run in a terminal.")
    print(f"{label}: ", end="", file=sys.stderr, flush=True)
    return sys.stdin.readline()


def _ask(label: str, *, prompt: Callable[[str], str]) -> str:
    return prompt(label).strip()


def _uuid_value(
    label: str,
    provided: str | None,
    *,
    prompt: Callable[[str], str],
    optional: bool = False,
) -> str | None:
    if provided is not None:
        text = provided.strip()
        if not text:
            if optional:
                return None
            raise ValueError(f"{label} must be a UUID")
        return _parse_uuid(label, text)
    text = _ask(label, prompt=prompt)
    if not text:
        if optional:
            return None
        raise ValueError(f"{label} must be a UUID")
    return _parse_uuid(label, text)


def _text_value(
    label: str,
    provided: str | None,
    *,
    prompt: Callable[[str], str],
) -> str:
    if provided is not None:
        return provided.strip()
    return _ask(label, prompt=prompt)


def _job_flag(
    args: argparse.Namespace,
    job: MappingJob,
    *,
    shared: str,
    per_marketplace: dict[MarketplaceId, str],
    allow_shared: bool,
) -> str | None:
    specific = getattr(args, per_marketplace[job.marketplace_id], None)
    if specific is not None:
        return specific
    if allow_shared:
        return getattr(args, shared, None)
    return None


def jobs_from_args(args: argparse.Namespace) -> list[MappingJob]:
    only = _parse_only(getattr(args, "only", None))
    single = args.marketplace is not None or args.xlsm is not None or args.out is not None
    all_at_once = any(
        (
            args.out_dir is not None,
            args.amazon_xlsm is not None,
            args.flipkart_xlsm is not None,
            args.myntra_xlsm is not None,
        )
    )
    if single and all_at_once:
        raise ValueError(
            "Use either --marketplace/--xlsm/--out or "
            "--amazon-xlsm/--flipkart-xlsm/--myntra-xlsm/--out-dir, not both"
        )
    if all_at_once:
        if args.out_dir is None:
            raise ValueError("All-at-once run requires --out-dir")
        candidates = (
            (
                MarketplaceId.AMAZON,
                args.amazon_xlsm,
                "amazon_listing_mapping.sql",
                args.amazon_sheet_name,
            ),
            (
                MarketplaceId.FLIPKART,
                args.flipkart_xlsm,
                "flipkart_listing_mapping.sql",
                args.flipkart_sheet_name,
            ),
            (
                MarketplaceId.MYNTRA,
                args.myntra_xlsm,
                "myntra_listing_mapping.sql",
                args.myntra_sheet_name,
            ),
        )
        provided = [item for item in candidates if item[1] is not None]
        if not provided:
            raise ValueError(
                "All-at-once run requires at least one of --amazon-xlsm, "
                "--flipkart-xlsm, or --myntra-xlsm"
            )
        out_dir = Path(args.out_dir)
        jobs = [
            MappingJob(
                marketplace_id,
                Path(xlsm),
                out_dir / out_name,
                sheet_name=sheet_name,
            )
            for marketplace_id, xlsm, out_name, sheet_name in provided
        ]
    elif args.marketplace is None or args.xlsm is None or args.out is None:
        raise ValueError("Single marketplace run requires --marketplace, --xlsm, and --out")
    else:
        jobs = [
            MappingJob(
                parse_marketplace_id(args.marketplace),
                Path(args.xlsm),
                Path(args.out),
                sheet_name=args.sheet_name,
                header_label_row=args.header_label_row,
                machine_key_row=args.machine_key_row,
                data_start_row=args.data_start_row,
            )
        ]

    if only is not None:
        selected = [job for job in jobs if job.marketplace_id in only]
        missing = sorted(
            marketplace.value
            for marketplace in only
            if marketplace not in {job.marketplace_id for job in selected}
        )
        if missing:
            raise ValueError(f"--only {', '.join(missing)} needs the matching listing workbook")
        jobs = selected
    if not jobs:
        raise ValueError("No marketplaces to generate. Pass a workbook or --only matching a file.")
    return jobs


def collect_apply_ids(
    args: argparse.Namespace,
    jobs: list[MappingJob],
    *,
    prompt: Callable[[str], str] = _stdin_prompt,
) -> list[tuple[MappingJob, ApplyIds]]:
    """Prompt (or take flags) only for jobs that will actually generate SQL."""
    category_id = _uuid_value(
        "category.external_id (UUID)",
        getattr(args, "category_external_id", None),
        prompt=prompt,
    )
    if category_id is None:
        raise ValueError("category.external_id must be a UUID")

    can_skip = len(jobs) > 1
    resolved: list[tuple[MappingJob, ApplyIds]] = []
    for job in jobs:
        name = job.marketplace_id.value
        marketplace_label = (
            f"{name} marketplace.external_id (UUID, Enter to skip)"
            if can_skip
            else f"{name} marketplace.external_id (UUID)"
        )
        marketplace_id = _uuid_value(
            marketplace_label,
            _job_flag(
                args,
                job,
                shared="marketplace_external_id",
                per_marketplace={
                    MarketplaceId.AMAZON: "amazon_marketplace_external_id",
                    MarketplaceId.FLIPKART: "flipkart_marketplace_external_id",
                    MarketplaceId.MYNTRA: "myntra_marketplace_external_id",
                },
                allow_shared=not can_skip,
            ),
            prompt=prompt,
            optional=can_skip,
        )
        if marketplace_id is None:
            print(f"Skipping {name}", file=sys.stderr)
            continue
        gcs_key = _text_value(
            f"{name} gcs_object_key (blank if listing_template already exists)",
            _job_flag(
                args,
                job,
                shared="gcs_object_key",
                per_marketplace={
                    MarketplaceId.AMAZON: "amazon_gcs_object_key",
                    MarketplaceId.FLIPKART: "flipkart_gcs_object_key",
                    MarketplaceId.MYNTRA: "myntra_gcs_object_key",
                },
                allow_shared=not can_skip,
            ),
            prompt=prompt,
        )
        resolved.append(
            (
                job,
                ApplyIds(
                    category_external_id=category_id,
                    marketplace_external_id=marketplace_id,
                    gcs_object_key=gcs_key,
                ),
            )
        )
    if not resolved:
        raise ValueError(
            "No marketplaces selected. Enter at least one marketplace.external_id "
            "or pass --only for the marketplace you want."
        )
    return resolved


def run_job(job: MappingJob, *, mapping: Path, apply_ids: ApplyIds) -> None:
    adapter = get_adapter(job.marketplace_id)
    layout = adapter.workbook_layout(
        sheet_name=job.sheet_name,
        header_label_row=job.header_label_row,
        machine_key_row=job.machine_key_row,
        data_start_row=job.data_start_row,
    )
    parsed = parse_mapping_workbook(mapping, job.marketplace_id)
    workbook_columns = build_columns(
        job.xlsm,
        layout=layout,
        include_requiredness=False,
    )
    result = overlay_columns(workbook_columns, parsed)
    sql = render_mapping_sql(
        columns=result.columns,
        attribute_spec=result.attribute_spec,
        layout=layout,
        xlsm_name=job.xlsm.name,
        mapping_name=mapping.name,
        marketplace_id=job.marketplace_id.value,
        apply_ids=apply_ids,
        warnings=result.warnings,
    )
    job.out.parent.mkdir(parents=True, exist_ok=True)
    job.out.write_text(sql, encoding="utf-8")
    by_fill: dict[str, int] = {}
    for col in result.columns:
        fill = col["config"]["fill_type"]
        by_fill[fill] = by_fill.get(fill, 0) + 1
    print(
        f"Wrote {job.out} ({len(result.columns)} columns, fill_types={by_fill}, "
        f"marketplace={job.marketplace_id.value}, "
        f"sheet={layout.sheet_name!r}, data_start_row={layout.data_start_row}, "
        f"allowed={len(result.attribute_spec['allowed'])}, "
        f"mandatory={len(result.attribute_spec['mandatory'])}, "
        f"warnings={len(result.warnings)})",
        file=sys.stderr,
    )
    for warning in result.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mapping",
        type=Path,
        required=True,
        help="Listing mapping Excel workbook (pim_contract + per-marketplace mapping sheets)",
    )
    parser.add_argument(
        "--marketplace",
        default=None,
        help="Single run: AMAZON | FLIPKART | MYNTRA",
    )
    parser.add_argument(
        "--xlsm",
        type=Path,
        default=None,
        help="Single run: blank marketplace listing workbook (.xlsx or .xlsm, not .xls)",
    )
    parser.add_argument("--out", type=Path, default=None, help="Single run: output SQL path")
    parser.add_argument("--sheet-name", default=None)
    parser.add_argument("--header-label-row", type=int, default=None)
    parser.add_argument("--machine-key-row", type=int, default=None)
    parser.add_argument("--data-start-row", type=int, default=None)
    parser.add_argument(
        "--amazon-xlsm",
        type=Path,
        default=None,
        help="All-at-once: Amazon blank listing workbook",
    )
    parser.add_argument(
        "--flipkart-xlsm",
        type=Path,
        default=None,
        help="All-at-once: Flipkart blank listing workbook (.xlsx or .xlsm, not .xls)",
    )
    parser.add_argument(
        "--myntra-xlsm",
        type=Path,
        default=None,
        help="All-at-once: Myntra blank listing workbook",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="All-at-once: directory for <marketplace>_listing_mapping.sql",
    )
    parser.add_argument("--amazon-sheet-name", default=None)
    parser.add_argument("--flipkart-sheet-name", default=None)
    parser.add_argument("--myntra-sheet-name", default=None)
    parser.add_argument(
        "--only",
        default=None,
        help=(
            "Comma-separated marketplaces to generate (AMAZON, FLIPKART, MYNTRA). "
            "Other workbooks on the command are ignored and not prompted."
        ),
    )
    parser.add_argument(
        "--category-external-id",
        default=None,
        help="categories.external_id (UUID). Prompted if omitted.",
    )
    parser.add_argument(
        "--marketplace-external-id",
        default=None,
        help="Shared marketplace.external_id when only one job runs. Prompted if omitted.",
    )
    parser.add_argument(
        "--gcs-object-key",
        default=None,
        help="Shared blank-workbook GCS key when only one job runs. Prompted if omitted.",
    )
    parser.add_argument("--amazon-marketplace-external-id", default=None)
    parser.add_argument("--flipkart-marketplace-external-id", default=None)
    parser.add_argument("--myntra-marketplace-external-id", default=None)
    parser.add_argument("--amazon-gcs-object-key", default=None)
    parser.add_argument("--flipkart-gcs-object-key", default=None)
    parser.add_argument("--myntra-gcs-object-key", default=None)
    args = parser.parse_args(argv)

    if not args.mapping.is_file():
        print(f"mapping workbook not found: {args.mapping}", file=sys.stderr)
        return 1
    for name, value in (
        ("--header-label-row", args.header_label_row),
        ("--machine-key-row", args.machine_key_row),
        ("--data-start-row", args.data_start_row),
    ):
        try:
            _positive_int(name, value)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    try:
        jobs = jobs_from_args(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for job in jobs:
        if not job.xlsm.is_file():
            print(f"listing workbook not found: {job.xlsm}", file=sys.stderr)
            return 1

    try:
        selected = collect_apply_ids(args, jobs)
        for job, apply_ids in selected:
            run_job(job, mapping=args.mapping, apply_ids=apply_ids)
    except (ValueError, OSError, FileNotFoundError, NotImplementedError) as exc:
        print(f"listing_mapping failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
