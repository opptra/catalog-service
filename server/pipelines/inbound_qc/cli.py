"""Laptop CLI for inbound content QC. Not mounted on the FastAPI app.

From ``server/``:

    python -m pipelines.inbound_qc.cli \\
        --product ../sample_data/one/bedsheet_mandatoryV1.csv \\
        --images ../sample_data/one/images.zip

Writes reports, then opens the review page. Use ``--no-review`` for CSVs only.
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from core.exceptions.inbound_qc import InboundQcError
from pipelines.inbound_qc.columns import checklist_from_headers
from pipelines.inbound_qc.extract import extract_prompt
from pipelines.inbound_qc.loaders import load_sku_bundles
from pipelines.inbound_qc.report import write_reports, write_sources
from pipelines.inbound_qc.run import run_inbound_qc
from pipelines.inbound_qc.types import Finding, SkuBundle, conflict_is_priority
from pipelines.inbound_qc.viewer import DEFAULT_HOST, DEFAULT_PORT, serve_review

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_REPORT_ROOT = _REPO_ROOT / "local-data" / "inbound-qc"
_DEFAULT_WORKERS = 8


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inbound QC: CSV vs product photos. Writes findings, then opens the review page."
        )
    )
    parser.add_argument("--product", type=Path, required=True, help="Product CSV/XLSX")
    parser.add_argument("--images", type=Path, required=True, help="Images ZIP (wizard layout)")
    parser.add_argument(
        "--sku-ids",
        default="",
        help="Comma-separated SKU ids to run (default: all rows)",
    )
    parser.add_argument(
        "--skip-vision",
        action="store_true",
        help="No OpenRouter (no extract, no judge)",
    )
    parser.add_argument("--workers", type=int, default=_DEFAULT_WORKERS)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_REPORT_ROOT,
        help="Report root (default: <repo>/local-data/inbound-qc)",
    )
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="Write CSVs only; do not start the review page",
    )
    parser.add_argument("--review-host", default=DEFAULT_HOST)
    parser.add_argument("--review-port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def _filter_bundles(bundles: list[SkuBundle], sku_ids_raw: str) -> list[SkuBundle]:
    wanted = {item.strip() for item in sku_ids_raw.split(",") if item.strip()}
    if not wanted:
        return bundles
    selected = [bundle for bundle in bundles if bundle.sku_id in wanted]
    missing = wanted - {bundle.sku_id for bundle in selected}
    if missing:
        raise InboundQcError(f"SKU id(s) not in product file: {sorted(missing)}")
    return selected


def _run_one(
    bundle: SkuBundle,
    *,
    client: OpenRouterClient | None,
    model: str | None,
    checklist_headers: list[str],
) -> list[Finding]:
    checklist = checklist_from_headers(checklist_headers, attributes=bundle.attributes)
    return run_inbound_qc(bundle, checklist, client=client, model=model)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    try:
        bundles = _filter_bundles(
            load_sku_bundles(args.product.expanduser(), args.images.expanduser()),
            args.sku_ids,
        )
    except InboundQcError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    client: OpenRouterClient | None = None
    model: str | None = None
    if not args.skip_vision:
        if not settings.openrouter_api_key:
            print("error: OPENROUTER_API_KEY is required unless --skip-vision", file=sys.stderr)
            return 2
        client = OpenRouterClient(settings.openrouter_api_key, settings.openrouter_base_url)
        model = settings.openrouter_inbound_qc_model

    headers = list(bundles[0].attributes) if bundles else []
    findings: list[Finding] = []
    workers = max(1, min(args.workers, len(bundles) or 1))

    logger.info(
        "Inbound QC SKUs=%s vision=%s workers=%s",
        len(bundles),
        client is not None,
        workers,
    )
    if client is not None and bundles:
        sample_prompt = extract_prompt(
            bundles[0],
            checklist_from_headers(headers, attributes=bundles[0].attributes),
        )
        print("vision prompt:", flush=True)
        print(sample_prompt, flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _run_one,
                bundle,
                client=client,
                model=model,
                checklist_headers=headers,
            ): bundle.sku_id
            for bundle in bundles
        }
        for future in as_completed(futures):
            sku_id = futures[future]
            try:
                findings.extend(future.result())
                logger.info("done %s", sku_id)
            except Exception as exc:  # noqa: BLE001 — isolate one SKU so the batch still writes
                logger.exception("SKU %s crashed", sku_id)
                findings.append(
                    Finding(
                        sku_id=sku_id,
                        severity="warning",
                        kind="error",
                        field="_run",
                        catalog_value="",
                        observed=str(exc)[:240],
                        notes="SKU crashed; others still reported",
                    )
                )

    findings.sort(
        key=lambda item: (
            item.sku_id,
            not conflict_is_priority(item.confidence, item.similarity),
            -(item.confidence or 0),
            item.similarity if item.similarity is not None else 100,
            item.kind,
            item.field,
        )
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.out_dir / stamp
    latest_dir = args.out_dir / "latest"
    sku_ids = [bundle.sku_id for bundle in bundles]
    product = args.product.expanduser()
    images = args.images.expanduser()
    findings_path, summary_path = write_reports(findings, sku_ids=sku_ids, directory=run_dir)
    write_reports(findings, sku_ids=sku_ids, directory=latest_dir)
    write_sources(run_dir, product=product, images=images)
    write_sources(latest_dir, product=product, images=images)
    print(f"findings: {findings_path}", flush=True)
    print(f"summary:  {summary_path}", flush=True)
    print(f"latest:   {latest_dir / 'findings.csv'}", flush=True)
    if args.no_review:
        print(f"review:   python -m pipelines.inbound_qc.viewer --report {latest_dir}", flush=True)
        return 0
    return serve_review(
        latest_dir,
        product=product,
        images=images,
        host=args.review_host,
        port=args.review_port,
        open_browser=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
