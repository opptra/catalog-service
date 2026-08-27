"""Run inbound QC for one SKU. FastAPI-free — CLI and a future job both call this."""

from __future__ import annotations

import logging

from core.clients.openrouter import OpenRouterClient
from core.exceptions.openrouter import OpenRouterError
from pipelines.inbound_qc.extract import extract_sku
from pipelines.inbound_qc.judge import build_judge_pairs, judge_pairs, structural_findings
from pipelines.inbound_qc.types import Checklist, Finding, SkuBundle

logger = logging.getLogger(__name__)


def run_inbound_qc(
    bundle: SkuBundle,
    checklist: Checklist,
    *,
    client: OpenRouterClient | None = None,
    model: str | None = None,
) -> list[Finding]:
    """Extract photos (if present), then a text judge. No LLM → no findings."""
    if client is None:
        return []
    if not model:
        raise ValueError("inbound QC model is required when a client is provided")

    findings: list[Finding] = []
    extract = None
    if not bundle.images:
        findings.append(
            Finding(
                sku_id=bundle.sku_id,
                severity="warning",
                kind="cross_modal",
                field="images",
                catalog_value="",
                observed="no images in ZIP for this SKU",
                notes="vision skipped",
            )
        )
    else:
        try:
            extract = extract_sku(client, bundle, checklist, model=model)
        except (OpenRouterError, ValueError, OSError) as exc:
            logger.exception("Inbound QC extract failed sku_id=%s", bundle.sku_id)
            findings.append(
                Finding(
                    sku_id=bundle.sku_id,
                    severity="warning",
                    kind="error",
                    field="_extract",
                    catalog_value="",
                    observed=str(exc)[:240],
                    notes="vision extract failed; judge still runs on catalog text",
                )
            )

    if extract is not None:
        findings.extend(structural_findings(bundle, extract))

    pairs = build_judge_pairs(bundle, checklist, extract)
    try:
        findings.extend(judge_pairs(client, pairs, model=model, sku_id=bundle.sku_id))
    except (OpenRouterError, ValueError, OSError) as exc:
        logger.exception("Inbound QC judge failed sku_id=%s", bundle.sku_id)
        findings.append(
            Finding(
                sku_id=bundle.sku_id,
                severity="warning",
                kind="error",
                field="_judge",
                catalog_value="",
                observed=str(exc)[:240],
                notes="judge failed; extract/structural findings still apply",
            )
        )
    return findings
