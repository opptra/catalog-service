"""Fill marketplace listing workbooks (.xlsx, .xlsm, and Excel 97-2003 .xls)."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from dto.listing_config import ListingTemplateMetadata

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK"
_XLS_MAX_COLS = 256
_XLS_MAX_ROWS = 65536

WorkbookKind = Literal["xls", "xlsx", "xlsm"]

_CONTENT_TYPES: dict[WorkbookKind, str] = {
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
}


@dataclass(frozen=True, slots=True)
class FilledListingFile:
    """Filled workbook bytes plus the name and content type to store/download."""

    content: bytes
    filename: str
    content_type: str


def workbook_from_xls_bytes(data: bytes) -> Workbook:
    """Load Excel 97-2003 .xls bytes into an openpyxl workbook (values only)."""
    try:
        import xlrd
    except ImportError as exc:
        raise ValueError(
            "Cannot read .xls listing templates: xlrd is not installed. "
            "Install it in the server venv (see server/requirements.txt)."
        ) from exc

    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception as exc:
        raise ValueError(f"Cannot read Excel 97-2003 listing template: {exc}") from exc

    workbook = Workbook()
    default = workbook.active
    for sheet_index, name in enumerate(book.sheet_names()):
        source = book.sheet_by_index(sheet_index)
        if sheet_index == 0:
            worksheet = default
            worksheet.title = name
        else:
            worksheet = workbook.create_sheet(title=name)
        for row in range(source.nrows):
            for col in range(source.ncols):
                text = _cell_text(source.cell_value(row, col))
                if text:
                    worksheet.cell(row + 1, col + 1, text)
    return workbook


def fill_workbook(
    template_bytes: bytes,
    *,
    metadata: ListingTemplateMetadata,
    rows: list[dict[int, str | None]],
) -> FilledListingFile:
    """Write SKU rows into a blank template and return downloadable workbook bytes.

    ``rows`` is a list of ``column_index → cell value`` maps (1-based Excel columns).
    ``.xlsm`` macros are preserved when present. ``.xls`` (Flipkart) is copied in
    place so colours, fonts, and other cell styles stay on the template.
    """
    kind = _detect_kind(template_bytes)
    if kind == "xls":
        content = _fill_xls(template_bytes, metadata=metadata, rows=rows)
    else:
        content = _fill_openxml(
            template_bytes,
            metadata=metadata,
            rows=rows,
            keep_vba=kind == "xlsm",
        )
    return FilledListingFile(
        content=content,
        filename=_filled_filename(metadata.filename, kind),
        content_type=_CONTENT_TYPES[kind],
    )


def listing_output_object_key(job_external_id: Any, filename: str) -> str:
    """GCS key for a filled listing workbook under a generation job."""
    safe_name = filename.strip() or "listing.xlsx"
    return f"jobs/{job_external_id}/output/listing/{safe_name}"


def _detect_kind(data: bytes) -> WorkbookKind:
    if not data:
        raise ValueError("Listing template file is empty")
    if data.startswith(_OLE_MAGIC):
        return "xls"
    if data.startswith(_ZIP_MAGIC):
        if _zip_has_vba(data):
            return "xlsm"
        return "xlsx"
    raise ValueError(
        "Listing template is not an Excel workbook (.xls / .xlsx / .xlsm). "
        f"Got {len(data)} bytes starting with {data[:8]!r}."
    )


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


def _fill_xls(
    data: bytes,
    *,
    metadata: ListingTemplateMetadata,
    rows: list[dict[int, str | None]],
) -> bytes:
    """Copy the original .xls and write data cells only, keeping template styles."""
    try:
        import xlrd
        from xlutils.filter import XLRDReader, XLWTWriter, process
    except ImportError as exc:
        raise ValueError(
            "Cannot fill .xls listing templates: xlrd and xlutils are required. "
            "Install them in the server venv (see server/requirements.txt)."
        ) from exc

    try:
        source_book = xlrd.open_workbook(file_contents=data, formatting_info=True)
    except Exception as exc:
        raise ValueError(f"Cannot read Excel 97-2003 listing template: {exc}") from exc

    names = source_book.sheet_names()
    if metadata.sheet_name not in names:
        raise ValueError(f"Sheet {metadata.sheet_name!r} not found in listing template")
    sheet_index = names.index(metadata.sheet_name)
    source_sheet = source_book.sheet_by_index(sheet_index)

    writer = XLWTWriter()
    process(XLRDReader(source_book, "listing.xls"), writer)
    dest_book = writer.output[0][1]
    style_list = writer.style_list
    dest_sheet = dest_book.get_sheet(sheet_index)

    for row_offset, values in enumerate(rows):
        excel_row = metadata.data_start_row + row_offset
        if excel_row > _XLS_MAX_ROWS:
            raise ValueError(
                f"Cannot write row {excel_row} to an .xls listing template "
                f"(max {_XLS_MAX_ROWS} rows)"
            )
        xl_row = excel_row - 1
        for column_index, cell_value in values.items():
            if cell_value is None:
                continue
            if column_index > _XLS_MAX_COLS:
                raise ValueError(
                    f"Cannot write column {column_index} to an .xls listing template "
                    f"(max {_XLS_MAX_COLS} columns)"
                )
            xl_col = column_index - 1
            style = _xls_cell_style(source_sheet, style_list, xl_row, xl_col)
            if style is None:
                dest_sheet.write(xl_row, xl_col, cell_value)
            else:
                dest_sheet.write(xl_row, xl_col, cell_value, style)

    out = io.BytesIO()
    dest_book.save(out)
    return out.getvalue()


def _xls_cell_style(source_sheet: Any, style_list: list[Any], row: int, col: int) -> Any | None:
    if row >= source_sheet.nrows or col >= source_sheet.ncols:
        return None
    try:
        xf_index = source_sheet.cell_xf_index(row, col)
    except Exception:
        return None
    if xf_index < 0 or xf_index >= len(style_list):
        return None
    return style_list[xf_index]


def _filled_filename(template_filename: str, kind: WorkbookKind) -> str:
    raw = template_filename.strip() or f"listing.{kind}"
    stem = Path(raw).stem or "listing"
    return f"{stem}_filled.{kind}"


def _cell_text(value: object | None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return ILLEGAL_CHARACTERS_RE.sub("", str(value)).strip()
