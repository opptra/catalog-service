"""Laptop CLI: pack unstructured catalog CSVs + Drive links for inbound QC.

From ``server/``:

    python -m pipelines.pack_inbound_inputs.cli \\
        --details ../sample_data/bombay-unst/BD-Details-FK.csv \\
        --images-csv "../sample_data/bombay-unst/Image Enhancement - Split.csv"
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from core.exceptions.pack_inbound_inputs import PackInboundInputsError
from pipelines.pack_inbound_inputs.drive import HttpxDriveStore
from pipelines.pack_inbound_inputs.pack import PackedInputs, pack_inbound_inputs

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DETAILS = _REPO_ROOT / "sample_data" / "bombay-unst" / "BD-Details-FK.csv"
_DEFAULT_IMAGES_CSV = _REPO_ROOT / "sample_data" / "bombay-unst" / "Image Enhancement - Split.csv"
_DEFAULT_OUT = _REPO_ROOT / "local-data" / "job-inputs" / "bombay-unst"


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Join unstructured product + image-link CSVs into attributes.csv + images.zip "
            "for inbound QC / the wizard."
        )
    )
    parser.add_argument("--details", type=Path, default=_DEFAULT_DETAILS)
    parser.add_argument("--images-csv", type=Path, default=_DEFAULT_IMAGES_CSV)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_OUT,
        help="Output directory (default: <repo>/local-data/job-inputs/bombay-unst)",
    )
    parser.add_argument("--limit", type=_positive_int, default=None, metavar="N")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Write attributes.csv and an empty images.zip (no Drive downloads)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    store: HttpxDriveStore | None = None
    try:
        if not args.skip_images:
            store = HttpxDriveStore()
        result = pack_inbound_inputs(
            args.details.expanduser(),
            args.images_csv.expanduser(),
            args.out_dir.expanduser(),
            store=store,
            skip_images=args.skip_images,
            limit=args.limit,
            workers=max(1, args.workers),
        )
    except PackInboundInputsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()
    _print_result(result)
    return 0


def _print_result(result: PackedInputs) -> None:
    print(f"skus:       {len(result.sku_ids)}")
    print(f"attributes: {result.attributes_csv}")
    print(f"images:     {result.images_zip}")
    if result.missing_image_sku_ids:
        print(f"no-images:  {len(result.missing_image_sku_ids)}")
    if result.failed_downloads:
        print(f"failed:     {len(result.failed_downloads)}")
    print(f"report:     {result.failures_csv}")


if __name__ == "__main__":
    raise SystemExit(main())
