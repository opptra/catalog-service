"""Laptop CLI: rebuild generation-pipeline input files from a job.

From ``server/``:

    python -m pipelines.export_job_inputs.cli --job-id <job-external-id>
    python -m pipelines.export_job_inputs.cli --job-id <job-external-id> --limit 5
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from uuid import UUID

from core.clients.db import DatabaseClient
from core.clients.gcs import GcsClient
from core.config import settings
from core.exceptions.export_job_inputs import JobInputExportError
from pipelines.export_job_inputs.export import JobInputExport, export_job_inputs

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_OUT_ROOT = _REPO_ROOT / "local-data" / "job-inputs"


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
            "Rebuild attributes.csv + images.zip for a GENERATION job "
            "(sku_master.attributes + GCS products/{SKU}/assets/images/)."
        )
    )
    parser.add_argument(
        "--job-id",
        required=True,
        help="job.external_id (UUID)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: <repo>/local-data/job-inputs/<job-id>)",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        metavar="N",
        help="Export only the first N SKUs in job order (default: all)",
    )
    return parser.parse_args(argv)


def _parse_job_id(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise JobInputExportError(f"Invalid job external_id: {raw!r}") from exc


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    try:
        job_external_id = _parse_job_id(args.job_id)
        if not settings.gcs_bucket:
            raise JobInputExportError("GCS_BUCKET is not set")

        out_dir = (
            args.out_dir.expanduser()
            if args.out_dir is not None
            else _DEFAULT_OUT_ROOT / str(job_external_id)
        )
        result = _export(job_external_id, out_dir, limit=args.limit)
    except JobInputExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"skus:       {len(result.sku_ids)}")
    print(f"attributes: {result.attributes_csv}")
    print(f"images:     {result.images_zip}")
    if result.missing_image_sku_ids:
        print(f"no-images:  {', '.join(result.missing_image_sku_ids)}")
    return 0


def _export(job_external_id: UUID, out_dir: Path, *, limit: int | None = None) -> JobInputExport:
    bucket = settings.gcs_bucket
    if not bucket:
        raise JobInputExportError("GCS_BUCKET is not set")
    logger.info("connecting catalog DB + GCS bucket=%s", bucket)
    catalog_db = DatabaseClient(settings.catalog_database_url)
    try:
        gcs = GcsClient(bucket)
        with catalog_db.session_factory() as session:
            return export_job_inputs(session, gcs, job_external_id, out_dir, limit=limit)
    finally:
        catalog_db.close()


if __name__ == "__main__":
    raise SystemExit(main())
