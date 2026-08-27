"""Map a QC report directory + product file + images ZIP into review payloads."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.exceptions.inbound_qc import InboundQcError
from pipelines.inbound_qc.loaders import (
    list_sku_image_index,
    load_product_attributes,
    read_sku_image,
)
from pipelines.inbound_qc.types import CONFLICT_TYPE_LABELS, ImageRef, conflict_is_priority

_SKIPPED_KINDS = frozenset({"ocr"})


def split_image_files(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(";") if part.strip()]


def load_sources(report_dir: Path) -> tuple[Path, Path]:
    path = report_dir / "sources.json"
    if not path.is_file():
        raise InboundQcError(
            f"No sources.json in {report_dir}. Pass --product and --images, or re-run QC."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InboundQcError(f"Invalid sources.json: {exc}") from exc
    product = Path(str(payload.get("product") or "")).expanduser()
    images = Path(str(payload.get("images") or "")).expanduser()
    if not product.is_file() or not images.is_file():
        raise InboundQcError(
            "sources.json paths are missing on disk. Pass --product and --images explicitly."
        )
    return product, images


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise InboundQcError(f"Report file not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            {
                str(key).strip(): str(value).strip() if value is not None else ""
                for key, value in row.items()
            }
            for row in csv.DictReader(handle)
        ]


def load_findings(report_dir: Path) -> list[dict[str, str]]:
    rows = _read_csv_rows(report_dir / "findings.csv")
    return [row for row in rows if row.get("kind") not in _SKIPPED_KINDS]


def load_summary(report_dir: Path) -> list[dict[str, str]]:
    return _read_csv_rows(report_dir / "summary.csv")


def _severity_rank(items: list[dict[str, str]]) -> str:
    severities = {row.get("severity", "") for row in items}
    if "blocker" in severities:
        return "blocker"
    if "warning" in severities:
        return "warning"
    if items:
        return "info"
    return ""


def _opt_int(raw: str) -> int | None:
    text = raw.strip()
    if text.isdigit():
        return int(text)
    return None


def finding_payload(row: dict[str, str]) -> dict[str, Any]:
    files = split_image_files(row.get("image_files", ""))
    confidence = _opt_int(row.get("confidence", ""))
    similarity = _opt_int(row.get("similarity", ""))
    kind = row.get("kind", "")
    priority = row.get("severity") == "blocker" or conflict_is_priority(confidence, similarity)
    return {
        "sku_id": row.get("sku_id", ""),
        "severity": row.get("severity", ""),
        "kind": kind,
        "conflict_type": CONFLICT_TYPE_LABELS.get(kind, kind),
        "field": row.get("field", ""),
        "catalog_value": row.get("catalog_value", ""),
        "observed": row.get("observed", ""),
        "visibility": row.get("visibility", ""),
        "confidence": confidence,
        "similarity": similarity,
        "priority": priority,
        "image_files": files,
        "observation_1": row.get("observation_1", ""),
        "observation_2": row.get("observation_2", ""),
        "notes": row.get("notes", ""),
        "manager_verdict": row.get("manager_verdict", ""),
        "manager_note": row.get("manager_note", ""),
    }


def _finding_sort_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
    similarity = item.get("similarity")
    return (
        0 if item.get("priority") else 1,
        -(item.get("confidence") or 0),
        similarity if similarity is not None else 100,
        str(item.get("field") or ""),
    )


def _sku_summary_row(sku_id: str, items: list[dict[str, str]]) -> dict[str, Any]:
    payloads = [finding_payload(row) for row in items]
    kinds = sorted({row.get("kind", "") for row in items if row.get("kind")})
    certainties = [item["confidence"] for item in payloads if item["confidence"] is not None]
    return {
        "sku_id": sku_id,
        "finding_count": len(items),
        "warning_count": sum(1 for row in items if row.get("severity") == "warning"),
        "blocker_count": sum(1 for row in items if row.get("severity") == "blocker"),
        "priority_count": sum(1 for item in payloads if item["priority"]),
        "max_certainty": max(certainties) if certainties else None,
        "max_severity": _severity_rank(items),
        "kinds": kinds,
    }


@dataclass(frozen=True, slots=True)
class ReviewStore:
    report_dir: Path
    product_path: Path
    images_path: Path
    findings: list[dict[str, str]]
    summary: list[dict[str, str]]
    attributes_by_sku: dict[str, dict[str, str]]
    images_by_sku: dict[str, list[ImageRef]]

    @classmethod
    def open(
        cls,
        report_dir: Path,
        *,
        product: Path | None = None,
        images: Path | None = None,
    ) -> ReviewStore:
        report_dir = report_dir.expanduser().resolve()
        if not report_dir.is_dir():
            raise InboundQcError(f"Report directory not found: {report_dir}")
        if product is None or images is None:
            sourced_product, sourced_images = load_sources(report_dir)
            product = product or sourced_product
            images = images or sourced_images
        product = product.expanduser().resolve()
        images = images.expanduser().resolve()
        return cls(
            report_dir=report_dir,
            product_path=product,
            images_path=images,
            findings=load_findings(report_dir),
            summary=load_summary(report_dir),
            attributes_by_sku=load_product_attributes(product),
            images_by_sku=list_sku_image_index(images),
        )

    def _findings_by_sku(self) -> dict[str, list[dict[str, str]]]:
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.findings:
            sku_id = row.get("sku_id", "")
            if sku_id:
                grouped[sku_id].append(row)
        return grouped

    def batch_payload(self) -> dict[str, Any]:
        by_sku = self._findings_by_sku()
        sku_ids: list[str] = []
        seen: set[str] = set()
        for row in self.summary:
            sku_id = row.get("sku_id", "")
            if sku_id and sku_id not in seen:
                seen.add(sku_id)
                sku_ids.append(sku_id)
        for sku_id in self.attributes_by_sku:
            if sku_id not in seen:
                seen.add(sku_id)
                sku_ids.append(sku_id)

        skus = [_sku_summary_row(sku_id, by_sku.get(sku_id, [])) for sku_id in sku_ids]
        skus.sort(
            key=lambda item: (
                -(item["priority_count"]),
                -(item["max_certainty"] or 0),
                item["sku_id"],
            )
        )
        with_findings = sum(1 for item in skus if item["finding_count"] > 0)
        blockers = sum(1 for item in skus if item["blocker_count"] > 0)
        priority = sum(1 for item in skus if item["priority_count"] > 0)
        return {
            "report_dir": str(self.report_dir),
            "product": str(self.product_path),
            "images": str(self.images_path),
            "sku_count": len(skus),
            "skus_with_findings": with_findings,
            "skus_with_blockers": blockers,
            "skus_with_priority": priority,
            "finding_count": len(self.findings),
            "skus": skus,
        }

    def sku_payload(self, sku_id: str) -> dict[str, Any]:
        known = (
            sku_id in self.attributes_by_sku
            or sku_id in self.images_by_sku
            or any(row.get("sku_id") == sku_id for row in self.summary)
            or any(row.get("sku_id") == sku_id for row in self.findings)
        )
        if not known:
            raise InboundQcError(f"SKU not found: {sku_id}")
        attributes = self.attributes_by_sku.get(sku_id, {})
        photos = self.images_by_sku.get(sku_id, [])
        sku_findings = self._findings_by_sku().get(sku_id, [])
        items = [finding_payload(row) for row in sku_findings]
        items.sort(key=_finding_sort_key)
        flagged: set[str] = set()
        for item in items:
            flagged.update(item["image_files"])
        return {
            **_sku_summary_row(sku_id, sku_findings),
            "attributes": [{"name": name, "value": value} for name, value in attributes.items()],
            "images": [
                {
                    "filename": photo.filename,
                    "content_type": photo.content_type,
                    "flagged": photo.filename in flagged,
                }
                for photo in photos
            ],
            "findings": items,
        }

    def image(self, sku_id: str, filename: str) -> ImageRef:
        return read_sku_image(self.images_path, sku_id, filename)
