"""Load SKU bundles from a product spreadsheet + images ZIP (same contract as the wizard)."""

from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath

from core.exceptions.inbound_qc import InboundQcError
from pipelines.inbound_qc.types import ImageRef, SkuBundle
from utils.flatfile import parse_template_rows

_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
_CONTENT_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def _is_ignored_name(name: str) -> bool:
    return name == "__MACOSX" or name.startswith(".")


def _path_parts(path: str) -> list[str]:
    return [part for part in path.replace("\\", "/").split("/") if part]


def _collect_top_levels(names: list[str]) -> set[str]:
    top: set[str] = set()
    for name in names:
        parts = _path_parts(name)
        if not parts or _is_ignored_name(parts[0]):
            continue
        top.add(parts[0])
    return top


def _root_prefix(top_levels: set[str]) -> str | None:
    if len(top_levels) != 1:
        return None
    return next(iter(top_levels))


def _iter_sku_image_members(archive: zipfile.ZipFile) -> list[tuple[str, str, str]]:
    """(sku_id, filename, zip member path) for every product photo in the archive."""
    names = archive.namelist()
    root = _root_prefix(_collect_top_levels(names))
    entries: list[tuple[str, str, str]] = []
    for name in names:
        info = archive.getinfo(name)
        if info.is_dir():
            continue
        parts = _path_parts(name)
        if not parts or _is_ignored_name(parts[0]):
            continue
        if root is not None:
            if parts[0] != root:
                continue
            relative = parts[1:]
        else:
            relative = parts
        if len(relative) < 2:
            continue
        sku_id = relative[0]
        filename = relative[-1]
        if _is_ignored_name(sku_id) or _is_ignored_name(filename):
            continue
        suffix = PurePosixPath(filename).suffix.lower()
        if suffix not in _IMAGE_EXT:
            continue
        entries.append((sku_id, filename, name))
    return entries


def _read_zip_images(zip_path: Path) -> dict[str, list[ImageRef]]:
    if not zip_path.is_file():
        raise InboundQcError(f"Images ZIP not found: {zip_path}")

    with zipfile.ZipFile(zip_path) as archive:
        by_sku: dict[str, list[ImageRef]] = {}
        for sku_id, filename, member in _iter_sku_image_members(archive):
            suffix = PurePosixPath(filename).suffix.lower()
            by_sku.setdefault(sku_id, []).append(
                ImageRef(
                    filename=filename,
                    content=archive.read(member),
                    content_type=_CONTENT_TYPE.get(suffix, "image/jpeg"),
                )
            )
    return by_sku


def list_sku_image_index(zip_path: Path) -> dict[str, list[ImageRef]]:
    """Filenames and content types only — does not read image bytes."""
    if not zip_path.is_file():
        raise InboundQcError(f"Images ZIP not found: {zip_path}")

    with zipfile.ZipFile(zip_path) as archive:
        by_sku: dict[str, list[ImageRef]] = {}
        for sku_id, filename, _member in _iter_sku_image_members(archive):
            suffix = PurePosixPath(filename).suffix.lower()
            by_sku.setdefault(sku_id, []).append(
                ImageRef(
                    filename=filename,
                    content_type=_CONTENT_TYPE.get(suffix, "image/jpeg"),
                )
            )
    return by_sku


def read_sku_image(zip_path: Path, sku_id: str, filename: str) -> ImageRef:
    """Read one photo from the ZIP. ``filename`` must be a basename, not a path."""
    if (
        not filename
        or "/" in filename
        or "\\" in filename
        or filename in {".", ".."}
        or Path(filename).name != filename
    ):
        raise InboundQcError("invalid image filename")
    if not zip_path.is_file():
        raise InboundQcError(f"Images ZIP not found: {zip_path}")

    with zipfile.ZipFile(zip_path) as archive:
        for entry_sku, entry_name, member in _iter_sku_image_members(archive):
            if entry_sku == sku_id and entry_name == filename:
                suffix = PurePosixPath(filename).suffix.lower()
                return ImageRef(
                    filename=filename,
                    content=archive.read(member),
                    content_type=_CONTENT_TYPE.get(suffix, "image/jpeg"),
                )
    raise InboundQcError(f"Image not found for SKU {sku_id}: {filename}")


def load_product_attributes(product_path: Path) -> dict[str, dict[str, str]]:
    """SKU id → spreadsheet row. Does not open the images ZIP."""
    if not product_path.is_file():
        raise InboundQcError(f"Product file not found: {product_path}")

    headers, rows = parse_template_rows(product_path.read_bytes(), filename=product_path.name)
    if "SKU" not in headers:
        raise InboundQcError("Product file is missing a SKU column")

    by_sku: dict[str, dict[str, str]] = {}
    for row in rows:
        sku_id = (row.get("SKU") or "").strip()
        if not sku_id or sku_id in by_sku:
            continue
        by_sku[sku_id] = dict(row)
    if not by_sku:
        raise InboundQcError("Product file has no SKU rows")
    return by_sku


def load_sku_bundles(product_path: Path, zip_path: Path) -> list[SkuBundle]:
    """Parse the spreadsheet and pair each SKU row with photos from the ZIP."""
    attributes = load_product_attributes(product_path)
    images_by_sku = _read_zip_images(zip_path)
    return [
        SkuBundle(
            sku_id=sku_id,
            attributes=row,
            images=tuple(images_by_sku.get(sku_id, ())),
        )
        for sku_id, row in attributes.items()
    ]
