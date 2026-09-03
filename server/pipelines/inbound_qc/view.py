"""Map a QC report directory + product file + images ZIP into review payloads."""

from __future__ import annotations

import csv
import json
import re
import threading
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from core.exceptions.inbound_qc import InboundQcError
from pipelines.inbound_qc.loaders import (
    index_open_zip,
    list_sku_image_index,
    load_product_attributes,
)
from pipelines.inbound_qc.types import CONFLICT_TYPE_LABELS, ImageRef, conflict_is_priority
from utils.flatfile import parse_template_rows
from utils.srgb_jpeg import JPEG_CONTENT_TYPE, for_browser_preview

_SKIPPED_KINDS = frozenset({"ocr"})
IMAGE_LINKS_COLUMN = "Image links"
ISSUE_COLUMN = "Issue"
LISTED_COLUMN = "Listed"
PHOTOS_COLUMN = "In photos"
WHY_COLUMN = "Why"
PRIORITY_EXPORT_NAME = "attributes_with_priority_issues.csv"
_IMAGE_INDEX = re.compile(r"^image_(\d+)", re.IGNORECASE)
_IMAGE_LINK_HEADERS = ("image link", "image drive", "image url")
_SIDE_LABEL = re.compile(
    r"^(?:catalog|photos?|image|other text)\b[^:]{0,40}:\s*",
    re.IGNORECASE,
)


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


def compact_finding(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "field": item.get("field", ""),
        "severity": item.get("severity", ""),
        "conflict_type": item.get("conflict_type", ""),
        "catalog_value": item.get("catalog_value", ""),
        "observed": item.get("observed", ""),
        "notes": item.get("notes", ""),
        "confidence": item.get("confidence"),
        "priority": bool(item.get("priority")),
    }


def format_finding_line(item: dict[str, Any]) -> str:
    field = str(item.get("field") or item.get("conflict_type") or "finding").strip()
    if item.get("priority"):
        field = f"{field} [priority]"
    catalog = str(item.get("catalog_value") or item.get("observation_1") or "").strip()
    observed = str(item.get("observed") or item.get("observation_2") or "").strip()
    notes = str(item.get("notes") or "").strip()
    bits = [field]
    if catalog and observed:
        bits.append(f"{catalog} → {observed}")
    elif catalog or observed:
        bits.append(catalog or observed)
    if notes:
        bits.append(notes)
    confidence = item.get("confidence")
    if isinstance(confidence, int):
        bits.append(f"{confidence}% certain")
    return " — ".join(bits)


def _plain_side(raw: object) -> str:
    text = " ".join(str(raw or "").split())
    return _SIDE_LABEL.sub("", text).strip()


def _manager_why(raw: object) -> str:
    text = " ".join(str(raw or "").split())
    if " Scores:" in text:
        text = text.split(" Scores:", 1)[0].strip()
    if text.casefold().startswith("scores:"):
        return ""
    return text


def priority_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item.get("priority")]


def _is_http_url(value: str) -> bool:
    key = value.strip().lower()
    return key.startswith("http://") or key.startswith("https://")


def urls_from_row(row: dict[str, str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for name, value in row.items():
        key = " ".join(name.strip().lower().split())
        if key != "image links" and not any(marker in key for marker in _IMAGE_LINK_HEADERS):
            continue
        for part in split_image_files(value):
            text = part.strip()
            if _is_http_url(text) and text not in seen:
                seen.add(text)
                urls.append(text)
    return urls


def load_sidecar_image_links(product_path: Path) -> dict[str, list[str]]:
    path = product_path.with_name("image_links.csv")
    if not path.is_file():
        return {}
    out: dict[str, list[str]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            sku_id = (row.get("SKU") or "").strip()
            if sku_id:
                out[sku_id] = split_image_files(row.get("Image links") or "")
    return out


def _urls_for_cited(urls: list[str], cited: list[str]) -> list[str]:
    picked: list[str] = []
    seen: set[str] = set()
    for name in cited:
        if _is_http_url(name):
            if name not in seen:
                seen.add(name)
                picked.append(name)
            continue
        match = _IMAGE_INDEX.match(name)
        if match is None:
            continue
        index = int(match.group(1)) - 1
        if 0 <= index < len(urls) and urls[index] not in seen:
            seen.add(urls[index])
            picked.append(urls[index])
    return picked


def format_image_links_cell(
    sku_id: str,
    row: dict[str, str],
    *,
    urls_by_sku: dict[str, list[str]],
    cited: list[str],
    zip_names: list[str],
) -> str:
    urls = list(urls_by_sku.get(sku_id) or []) or urls_from_row(row)
    if urls:
        relevant = _urls_for_cited(urls, cited)
        return "; ".join(relevant or urls)
    names = cited or zip_names
    return "; ".join(names)


def build_attributes_with_findings_csv(
    product_path: Path,
    findings: list[dict[str, str]],
    *,
    images_by_sku: dict[str, list[ImageRef]] | None = None,
) -> bytes:
    """Attribute rows for SKUs with priority issues. One readable row per issue."""
    headers, rows = parse_template_rows(product_path.read_bytes(), filename=product_path.name)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in findings:
        sku_id = row.get("sku_id", "")
        if sku_id:
            grouped[sku_id].append(finding_payload(row))
    for items in grouped.values():
        items.sort(key=_finding_sort_key)
    urls_by_sku = load_sidecar_image_links(product_path)
    photos = images_by_sku or {}
    fieldnames = list(headers)
    for name in (ISSUE_COLUMN, LISTED_COLUMN, PHOTOS_COLUMN, WHY_COLUMN, IMAGE_LINKS_COLUMN):
        if name not in fieldnames:
            fieldnames.append(name)
    buffer = StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=fieldnames,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        sku_id = (row.get("SKU") or "").strip()
        zip_names = [photo.filename for photo in photos.get(sku_id, [])]
        for item in priority_items(grouped.get(sku_id, [])):
            out = dict(row)
            out[ISSUE_COLUMN] = str(item.get("field") or "").strip()
            out[LISTED_COLUMN] = _plain_side(
                item.get("catalog_value") or item.get("observation_1") or ""
            )
            out[PHOTOS_COLUMN] = _plain_side(
                item.get("observed") or item.get("observation_2") or ""
            )
            out[WHY_COLUMN] = _manager_why(item.get("notes") or "")
            cited = [str(name) for name in item.get("image_files") or [] if name]
            out[IMAGE_LINKS_COLUMN] = format_image_links_cell(
                sku_id,
                row,
                urls_by_sku=urls_by_sku,
                cited=cited,
                zip_names=zip_names,
            )
            writer.writerow(out)
    return buffer.getvalue().encode("utf-8")


def write_attributes_with_findings(
    directory: Path,
    *,
    product_path: Path,
    findings: list[dict[str, str]],
    images_path: Path | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    photos = list_sku_image_index(images_path) if images_path is not None else None
    path = directory / PRIORITY_EXPORT_NAME
    path.write_bytes(
        build_attributes_with_findings_csv(product_path, findings, images_by_sku=photos)
    )
    return path


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
    payloads.sort(key=_finding_sort_key)
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
        "findings_preview": [compact_finding(item) for item in payloads],
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
    _preview_cache: dict[tuple[str, str], ImageRef]
    _zip_members: dict[tuple[str, str], str]
    _archive: zipfile.ZipFile
    _zip_lock: threading.Lock

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
        if not images.is_file():
            raise InboundQcError(f"Images ZIP not found: {images}")
        archive = zipfile.ZipFile(images)
        try:
            photos, members = index_open_zip(archive)
        except Exception:
            archive.close()
            raise
        return cls(
            report_dir=report_dir,
            product_path=product,
            images_path=images,
            findings=load_findings(report_dir),
            summary=load_summary(report_dir),
            attributes_by_sku=load_product_attributes(product),
            images_by_sku=photos,
            _preview_cache={},
            _zip_members=members,
            _archive=archive,
            _zip_lock=threading.Lock(),
        )

    def close(self) -> None:
        with self._zip_lock:
            self._archive.close()

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
                    "content_type": (
                        JPEG_CONTENT_TYPE
                        if photo.content_type in {"image/tiff", "image/bmp"}
                        else photo.content_type
                    ),
                    "flagged": photo.filename in flagged,
                }
                for photo in photos
            ],
            "findings": items,
        }

    def attributes_csv_with_findings(self) -> bytes:
        return build_attributes_with_findings_csv(
            self.product_path,
            self.findings,
            images_by_sku=self.images_by_sku,
        )

    def image(self, sku_id: str, filename: str) -> ImageRef:
        key = (sku_id, filename)
        cached = self._preview_cache.get(key)
        if cached is not None:
            return cached
        member = self._zip_members.get(key)
        if member is None:
            raise InboundQcError(f"Image not found for SKU {sku_id}: {filename}")
        with self._zip_lock:
            raw = self._archive.read(member)
        photos = self.images_by_sku.get(sku_id, [])
        listed = next((photo for photo in photos if photo.filename == filename), None)
        content_type = listed.content_type if listed is not None else "image/jpeg"
        content, content_type = for_browser_preview(raw, content_type)
        preview = ImageRef(filename=filename, content=content, content_type=content_type)
        self._preview_cache[key] = preview
        return preview
