"""Write inbound QC findings and per-SKU summary CSVs."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from pipelines.inbound_qc.types import Finding

_FINDING_FIELDS = (
    "sku_id",
    "severity",
    "kind",
    "field",
    "catalog_value",
    "observed",
    "visibility",
    "confidence",
    "similarity",
    "image_files",
    "observation_1",
    "observation_2",
    "notes",
    "manager_verdict",
    "manager_note",
)

_SUMMARY_FIELDS = (
    "sku_id",
    "finding_count",
    "warning_count",
    "blocker_count",
    "max_severity",
    "kinds",
)


def _finding_row(finding: Finding) -> dict[str, str]:
    return {
        "sku_id": finding.sku_id,
        "severity": finding.severity,
        "kind": finding.kind,
        "field": finding.field,
        "catalog_value": finding.catalog_value,
        "observed": finding.observed,
        "visibility": finding.visibility,
        "confidence": "" if finding.confidence is None else str(finding.confidence),
        "similarity": "" if finding.similarity is None else str(finding.similarity),
        "image_files": finding.image_files,
        "observation_1": finding.observation_1,
        "observation_2": finding.observation_2,
        "notes": finding.notes,
        "manager_verdict": finding.manager_verdict,
        "manager_note": finding.manager_note,
    }


def write_reports(
    findings: list[Finding],
    *,
    sku_ids: list[str],
    directory: Path,
) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    findings_path = directory / "findings.csv"
    summary_path = directory / "summary.csv"

    with findings_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FINDING_FIELDS)
        writer.writeheader()
        for finding in findings:
            writer.writerow(_finding_row(finding))

    by_sku: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        by_sku[finding.sku_id].append(finding)

    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_SUMMARY_FIELDS)
        writer.writeheader()
        for sku_id in sku_ids:
            rows = by_sku.get(sku_id, [])
            severities = {item.severity for item in rows}
            if "blocker" in severities:
                max_severity = "blocker"
            elif "warning" in severities:
                max_severity = "warning"
            elif rows:
                max_severity = "info"
            else:
                max_severity = ""
            writer.writerow(
                {
                    "sku_id": sku_id,
                    "finding_count": str(len(rows)),
                    "warning_count": str(sum(1 for item in rows if item.severity == "warning")),
                    "blocker_count": str(sum(1 for item in rows if item.severity == "blocker")),
                    "max_severity": max_severity,
                    "kinds": ";".join(sorted({item.kind for item in rows})),
                }
            )

    return findings_path, summary_path


def write_sources(directory: Path, *, product: Path, images: Path) -> Path:
    """Record the product file and images ZIP used for this report (viewer input)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sources.json"
    payload = {
        "product": str(product.resolve()),
        "images": str(images.resolve()),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
