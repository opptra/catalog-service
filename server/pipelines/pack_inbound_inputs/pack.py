"""Join unstructured catalog CSVs + Drive links into wizard inbound-QC inputs."""

from __future__ import annotations

import csv
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from core.exceptions.pack_inbound_inputs import PackInboundInputsError
from pipelines.pack_inbound_inputs.drive import (
    DriveFileStore,
    drive_file_id,
    image_suffix,
    looks_like_image,
)

logger = logging.getLogger(__name__)

ATTRIBUTES_CSV_NAME = "attributes.csv"
IMAGES_ZIP_NAME = "images.zip"
FAILURES_CSV_NAME = "pack_failures.csv"
IMAGE_LINKS_CSV_NAME = "image_links.csv"
_ZIP_ROOT = "images"

_SPLIT_IMAGE_HEADERS = ("Image Link 1", "Image Link 2", "Image link 3")
_DETAIL_IMAGE_HEADERS = (
    "Image drive link  -1",
    "Image drive link  -2",
    "Image drive link  -3",
    "Image drive link  -4",
)

# Source header → wizard / inbound-QC header. First mapping wins when dest repeats.
_ATTR_MAP: tuple[tuple[str, str], ...] = (
    ("Opptra SKU", "SKU"),
    ("Title", "Product Name / Title"),
    ("Product Description", "Product Description"),
    ("Product Name", "Product Name"),
    ("Product Description (2)", "Product Name"),
    ("Product Highlight", "Item Highlight"),
    ("Color", "Color"),
    ("S/D/K/SK", "Size"),
    ("S/D/K/SK", "Bed Size"),
    ("Size", "Bedsheet Size"),
    ("Design Style", "Pattern"),
    ("Material", "Material"),
    ("Sub Category", "Product Type"),
    ("Sub Category", "Sub-category"),
    ("Brand Name", "Brand Name"),
    ("EAN", "EAN / GTIN / Barcode"),
    ("HSN Code", "HSN Code"),
    ("MRP", "MRP"),
    ("Product Specs (TC/ GSM)", "Thread Count"),
    ("Included In Box", "Items Included"),
    ("Pack of 1/2", "Number of Items"),
    ("Print", "Print or Pattern Type"),
    ("Flat/ Fitted", "Bedding Set Type"),
    ("Brand - Series", "Collection Name"),
    ("Product Length (cm) - Item", "Item Length (CM)"),
    ("Product Width (cm) - Item", "Item Width (cm)"),
    ("Season Type", "Season Type"),
)

_OUTPUT_HEADERS = (
    "SKU",
    "Product Name / Title",
    "Product Description",
    "Item Highlight",
    "Color",
    "Size",
    "Bed Size",
    "Bedsheet Size",
    "Pattern",
    "Material",
    "Product Type",
    "Sub-category",
    "Brand Name",
    "EAN / GTIN / Barcode",
    "HSN Code",
    "MRP",
    "Thread Count",
    "Items Included",
    "Number of Items",
    "Print or Pattern Type",
    "Bedding Set Type",
    "Collection Name",
    "Item Length (CM)",
    "Item Width (cm)",
    "Product Name",
    "Season Type",
)


@dataclass(frozen=True, slots=True)
class PackedInputs:
    sku_ids: tuple[str, ...]
    attributes_csv: Path
    images_zip: Path
    missing_image_sku_ids: tuple[str, ...]
    failed_downloads: tuple[str, ...]
    failures_csv: Path


def _unique_headers(raw: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    headers: list[str] = []
    for name in raw:
        key = name.strip()
        count = seen.get(key, 0)
        seen[key] = count + 1
        headers.append(key if count == 0 else f"{key} ({count + 1})")
    return headers


def load_table(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PackInboundInputsError(f"File not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            raw_headers = next(reader)
        except StopIteration as exc:
            raise PackInboundInputsError(f"Empty CSV: {path}") from exc
        headers = _unique_headers(raw_headers)
        rows: list[dict[str, str]] = []
        for parts in reader:
            if not any(cell.strip() for cell in parts):
                continue
            row = {
                headers[index]: (parts[index].strip() if index < len(parts) else "")
                for index in range(len(headers))
            }
            rows.append(row)
    if not rows:
        raise PackInboundInputsError(f"No data rows in {path}")
    return rows


def _map_detail_row(raw: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = dict.fromkeys(_OUTPUT_HEADERS, "")
    for source, dest in _ATTR_MAP:
        value = (raw.get(source) or "").strip()
        if value and not out.get(dest):
            out[dest] = value
    return out


def _thin_split_row(raw: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = dict.fromkeys(_OUTPUT_HEADERS, "")
    out["SKU"] = (raw.get("Opptra SKU") or "").strip()
    out["EAN / GTIN / Barcode"] = (raw.get("EAN") or "").strip()
    out["Brand Name"] = (raw.get("Brand") or "").strip()
    sub = (raw.get("Sub Category") or "").strip()
    out["Product Type"] = sub
    out["Sub-category"] = sub
    out["Season Type"] = (raw.get("Season Type") or "").strip()
    return out


def _image_ids(*rows: dict[str, str]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for url in _image_urls(*rows):
        file_id = drive_file_id(url)
        if file_id and file_id not in seen:
            seen.add(file_id)
            ids.append(file_id)
    return ids


def _image_urls(*rows: dict[str, str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    headers = (*_SPLIT_IMAGE_HEADERS, *_DETAIL_IMAGE_HEADERS)
    for row in rows:
        for header in headers:
            url = (row.get(header) or "").strip()
            file_id = drive_file_id(url)
            if file_id and file_id not in seen:
                seen.add(file_id)
                urls.append(url)
    return urls


def build_rows(
    details: list[dict[str, str]],
    split: list[dict[str, str]],
    *,
    limit: int | None = None,
) -> tuple[list[dict[str, str]], dict[str, list[str]], dict[str, list[str]]]:
    details_by_sku = {
        (row.get("Opptra SKU") or "").strip(): row
        for row in details
        if (row.get("Opptra SKU") or "").strip()
    }
    split_by_sku = {
        (row.get("Opptra SKU") or "").strip(): row
        for row in split
        if (row.get("Opptra SKU") or "").strip()
    }
    ordered = [sku for sku in details_by_sku if sku]
    for sku in split_by_sku:
        if sku not in details_by_sku:
            ordered.append(sku)
    if limit is not None:
        ordered = ordered[:limit]

    rows: list[dict[str, str]] = []
    images: dict[str, list[str]] = {}
    urls: dict[str, list[str]] = {}
    for sku_id in ordered:
        detail = details_by_sku.get(sku_id)
        split_row = split_by_sku.get(sku_id)
        mapped = _map_detail_row(detail) if detail is not None else _thin_split_row(split_row or {})
        mapped["SKU"] = sku_id
        rows.append(mapped)
        sources = tuple(item for item in (split_row, detail) if item is not None)
        images[sku_id] = _image_ids(*sources)
        urls[sku_id] = _image_urls(*sources)
    if not rows:
        raise PackInboundInputsError("No Opptra SKU rows to pack")
    return rows, images, urls


def write_failures_csv(
    path: Path,
    *,
    failed: tuple[str, ...],
    missing_sku_ids: tuple[str, ...],
) -> Path:
    missing = set(missing_sku_ids)
    failed_skus: set[str] = set()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["sku", "status", "drive_file_id", "error", "no_images"],
        )
        writer.writeheader()
        for item in failed:
            sku_id, file_id, reason = _split_failed(item)
            failed_skus.add(sku_id)
            writer.writerow(
                {
                    "sku": sku_id,
                    "status": "failed",
                    "drive_file_id": file_id,
                    "error": reason,
                    "no_images": "yes" if sku_id in missing else "no",
                }
            )
        for sku_id in missing_sku_ids:
            if sku_id in failed_skus:
                continue
            writer.writerow(
                {
                    "sku": sku_id,
                    "status": "no_images",
                    "drive_file_id": "",
                    "error": "",
                    "no_images": "yes",
                }
            )
    return path


def _split_failed(item: str) -> tuple[str, str, str]:
    sku_id, rest = item.split(":", 1)
    if ":" in rest:
        file_id, reason = rest.split(":", 1)
        return sku_id, file_id, reason
    return sku_id, rest, ""


def write_attributes_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_OUTPUT_HEADERS), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_image_links_csv(path: Path, urls_by_sku: dict[str, list[str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["SKU", "Image links"])
        writer.writeheader()
        for sku_id, urls in urls_by_sku.items():
            writer.writerow({"SKU": sku_id, "Image links": "; ".join(urls)})
    return path


_CACHE_SUFFIXES = (".jpg", ".png", ".webp", ".gif", ".tif", ".tiff", ".bmp", ".bin")


def write_images_zip(path: Path, images_by_sku: dict[str, list[tuple[str, Path]]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for sku_id, files in images_by_sku.items():
            if not files:
                archive.writestr(f"{_ZIP_ROOT}/{sku_id}/", b"")
                continue
            for filename, source in files:
                archive.write(source, f"{_ZIP_ROOT}/{sku_id}/{filename}")
    return path


def _clear_partial_cache(cache_dir: Path) -> None:
    for part in cache_dir.glob("*.part"):
        part.unlink(missing_ok=True)


def _existing_cache(cache_dir: Path, file_id: str) -> Path | None:
    for suffix in _CACHE_SUFFIXES:
        cached = cache_dir / f"{file_id}{suffix}"
        if not cached.is_file() or cached.stat().st_size == 0:
            continue
        with cached.open("rb") as handle:
            head = handle.read(16)
        if len(head) >= 12 and looks_like_image(head):
            return cached
    return None


def _store_cache(cache_dir: Path, file_id: str, content: bytes) -> Path:
    dest = cache_dir / f"{file_id}{image_suffix(content)}"
    part = dest.with_name(f"{dest.name}.part")
    part.write_bytes(content)
    part.replace(dest)
    return dest


def _cached_download(store: DriveFileStore, file_id: str, cache_dir: Path) -> Path:
    existing = _existing_cache(cache_dir, file_id)
    if existing is not None:
        return existing
    content = store.download(file_id)
    dest = _store_cache(cache_dir, file_id, content)
    logger.info("downloaded %s (%s bytes)", file_id, dest.stat().st_size)
    return dest


def download_images(
    image_ids_by_sku: dict[str, list[str]],
    store: DriveFileStore,
    *,
    workers: int,
    cache_dir: Path,
) -> tuple[dict[str, list[tuple[str, Path]]], list[str], list[str]]:
    unique_ids = list(
        dict.fromkeys(file_id for ids in image_ids_by_sku.values() for file_id in ids)
    )
    images_by_sku: dict[str, list[tuple[str, Path]]] = {sku: [] for sku in image_ids_by_sku}
    paths: dict[str, Path] = {}
    failed_reasons: dict[str, str] = {}
    if not unique_ids:
        return images_by_sku, list(image_ids_by_sku), []

    cache_dir.mkdir(parents=True, exist_ok=True)
    _clear_partial_cache(cache_dir)
    to_fetch: list[str] = []
    for file_id in unique_ids:
        existing = _existing_cache(cache_dir, file_id)
        if existing is not None:
            paths[file_id] = existing
        else:
            to_fetch.append(file_id)
    logger.info("drive cache: %s hits, %s to download", len(paths), len(to_fetch))

    if to_fetch:
        workers = max(1, min(workers, len(to_fetch)))

        def _one(file_id: str) -> tuple[str, Path]:
            return file_id, _cached_download(store, file_id, cache_dir)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_one, file_id): file_id for file_id in to_fetch}
            for future in as_completed(futures):
                file_id = futures[future]
                try:
                    _, path = future.result()
                except Exception as exc:  # noqa: BLE001 — one Drive file must not stop the batch
                    logger.warning("download failed %s: %s", file_id, exc)
                    failed_reasons[file_id] = str(exc)
                    continue
                paths[file_id] = path

    failed: list[str] = []
    for sku_id, file_ids in image_ids_by_sku.items():
        for index, file_id in enumerate(file_ids, start=1):
            if file_id in failed_reasons:
                failed.append(f"{sku_id}:{file_id}:{failed_reasons[file_id]}")
                continue
            source = paths.get(file_id)
            if source is None:
                failed.append(f"{sku_id}:{file_id}:missing")
                continue
            filename = f"image_{index:02d}{source.suffix}"
            images_by_sku[sku_id].append((filename, source))

    missing = [sku_id for sku_id, files in images_by_sku.items() if not files]
    return images_by_sku, missing, failed


def pack_inbound_inputs(
    details_path: Path,
    images_csv_path: Path,
    out_dir: Path,
    *,
    store: DriveFileStore | None = None,
    skip_images: bool = False,
    limit: int | None = None,
    workers: int = 8,
    cache_dir: Path | None = None,
) -> PackedInputs:
    if limit is not None and limit < 1:
        raise PackInboundInputsError("limit must be a positive integer")
    details = load_table(details_path)
    split = load_table(images_csv_path)
    rows, image_ids, image_urls = build_rows(details, split, limit=limit)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = write_attributes_csv(out_dir / ATTRIBUTES_CSV_NAME, rows)
    write_image_links_csv(out_dir / IMAGE_LINKS_CSV_NAME, image_urls)

    images_by_sku: dict[str, list[tuple[str, Path]]] = {row["SKU"]: [] for row in rows}
    missing: list[str] = []
    failed: list[str] = []
    if skip_images:
        missing = [row["SKU"] for row in rows if not image_ids.get(row["SKU"])]
    else:
        if store is None:
            raise PackInboundInputsError("A Drive downloader is required unless --skip-images")
        cache = cache_dir if cache_dir is not None else out_dir / ".drive-cache"
        images_by_sku, missing, failed = download_images(
            image_ids,
            store,
            workers=workers,
            cache_dir=cache,
        )
    zip_path = write_images_zip(out_dir / IMAGES_ZIP_NAME, images_by_sku)
    missing_ids = tuple(missing)
    failed_ids = tuple(failed)
    failures_csv = write_failures_csv(
        out_dir / FAILURES_CSV_NAME,
        failed=failed_ids,
        missing_sku_ids=missing_ids,
    )
    return PackedInputs(
        sku_ids=tuple(row["SKU"] for row in rows),
        attributes_csv=csv_path,
        images_zip=zip_path,
        missing_image_sku_ids=missing_ids,
        failed_downloads=failed_ids,
        failures_csv=failures_csv,
    )
