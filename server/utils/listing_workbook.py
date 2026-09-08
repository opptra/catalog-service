"""Fill marketplace listing workbooks (.xlsx and .xlsm)."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook

from dto.listing_config import ListingTemplateMetadata

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK"
_XLS_REJECTED = (
    "Listing templates must be .xlsx or .xlsm. Convert a Flipkart .xls in Excel "
    "(File → Save As → Excel Macro-Enabled Workbook .xlsm to keep VBA, or .xlsx "
    "if macros are not needed) before upload; the server does not read .xls."
)

WorkbookKind = Literal["xlsx", "xlsm"]

_CONTENT_TYPES: dict[WorkbookKind, str] = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
}


def content_type_for(kind: WorkbookKind) -> str:
    return _CONTENT_TYPES[kind]


@dataclass(frozen=True, slots=True)
class FilledListingFile:
    """Filled workbook bytes plus the name and content type to store/download."""

    content: bytes
    filename: str
    content_type: str


def detect_openxml_kind(data: bytes) -> WorkbookKind:
    """Return xlsx/xlsm, or raise if the bytes are empty, .xls, or not Excel."""
    if not data:
        raise ValueError("Listing template file is empty")
    if data.startswith(_OLE_MAGIC):
        raise ValueError(_XLS_REJECTED)
    if data.startswith(_ZIP_MAGIC):
        if _zip_has_vba(data):
            return "xlsm"
        return "xlsx"
    raise ValueError(
        "Listing template is not an Excel workbook (.xlsx / .xlsm). "
        f"Got {len(data)} bytes starting with {data[:8]!r}."
    )


def fill_workbook(
    template_bytes: bytes,
    *,
    metadata: ListingTemplateMetadata,
    rows: list[dict[int, str | None]],
) -> FilledListingFile:
    """Write SKU rows into a blank template and return downloadable workbook bytes.

    ``rows`` is a list of ``column_index → cell value`` maps (1-based Excel columns).
    The template is edited in place (openpyxl). ``.xls`` is not supported;
    save as ``.xlsx`` or ``.xlsm`` in Excel first.
    """
    kind = detect_openxml_kind(template_bytes)
    content = _fill_openxml(
        template_bytes,
        metadata=metadata,
        rows=rows,
        keep_vba=kind == "xlsm",
    )
    return FilledListingFile(
        content=content,
        filename=_filled_filename(metadata.filename, kind),
        content_type=content_type_for(kind),
    )


def listing_output_object_key(job_external_id: Any, filename: str) -> str:
    """GCS key for a filled listing workbook under a generation job."""
    safe_name = filename.strip() or "listing.xlsx"
    return f"jobs/{job_external_id}/output/listing/{safe_name}"


def _zip_has_vba(data: bytes) -> bool:
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            return any(name.lower().endswith("vbaproject.bin") for name in archive.namelist())
    except Exception:
        return False


def _fill_openxml(
    data: bytes,
    *,
    metadata: ListingTemplateMetadata,
    rows: list[dict[int, str | None]],
    keep_vba: bool,
) -> bytes:
    workbook = _load_openxml(data, keep_vba=keep_vba)
    if metadata.sheet_name not in workbook.sheetnames:
        raise ValueError(f"Sheet {metadata.sheet_name!r} not found in listing template")
    sheet = workbook[metadata.sheet_name]
    for row_offset, values in enumerate(rows):
        excel_row = metadata.data_start_row + row_offset
        for column_index, cell_value in values.items():
            if cell_value is None:
                continue
            sheet.cell(excel_row, column_index, cell_value)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _load_openxml(data: bytes, *, keep_vba: bool) -> Workbook:
    buffer = io.BytesIO(data)
    try:
        return load_workbook(buffer, keep_vba=keep_vba)
    except Exception as exc:
        raise ValueError(f"Cannot read listing template workbook: {exc}") from exc


def _filled_filename(template_filename: str, kind: WorkbookKind) -> str:
    raw = template_filename.strip() or f"listing.{kind}"
    stem = Path(raw).stem or "listing"
    return f"{stem}_filled.{kind}"
