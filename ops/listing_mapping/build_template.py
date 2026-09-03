"""Build Excel-only listing mapping template.

One workbook, shared ``pim_contract`` + ``lists``. Each marketplace sheet
(``amazon_mapping``, ``flipkart_mapping``, ``myntra_mapping``) starts with
example rows for every fill_mode — not a filled category mapping.
"""

from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "ops") not in sys.path:
    sys.path.insert(0, str(_REPO / "ops"))
if str(_REPO / "server") not in sys.path:
    sys.path.insert(0, str(_REPO / "server"))

from entities.catalog.attribute_enums import AttributeName
from listing_mapping.marketplace import MAPPING_SHEET_NAMES

OUT_XLSX = _REPO / "ops" / "docs" / "listing_mapping_template.xlsx"

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF")
OK_FILL = PatternFill("solid", fgColor="C6EFCE")
ERR_FILL = PatternFill("solid", fgColor="FFC7CE")
ERR_FONT = Font(color="9C0006", bold=True)
TITLE_FONT = Font(bold=True, size=14, color="1F4E79")
SECTION_FONT = Font(bold=True, size=11, color="1F4E79")
BODY_FONT = Font(size=11)
THIN = Border(
    left=Side(style="thin", color="B0B0B0"),
    right=Side(style="thin", color="B0B0B0"),
    top=Side(style="thin", color="B0B0B0"),
    bottom=Side(style="thin", color="B0B0B0"),
)

PIM_ROWS = 80
# Max data rows per marketplace mapping sheet (header is row 1).
# Status formulas go through this ceiling so a new column_index still validates;
# blank index + blank fill_mode stays blank (no Excel 0). fill_mode is required
# once an index is present.
MKT_ROWS = 320

MAPPING_SHEETS: tuple[tuple[str, str], ...] = tuple(
    (marketplace_id.value, sheet_name)
    for marketplace_id, sheet_name in MAPPING_SHEET_NAMES.items()
)


def _style_header(ws, ncols: int) -> None:
    for col in range(1, ncols + 1):
        cell = ws.cell(1, col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.border = THIN
    ws.freeze_panes = "A2"


def _autosize(ws, widths: list[int]) -> None:
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def _set(ws, row: int, col: int, value: str | int | None) -> None:
    """Write a cell without creating empty inlineStr (Excel repair trigger)."""
    cell = ws.cell(row, col)
    cell.border = THIN
    if value is None or value == "":
        return
    cell.value = value


def _list_dv(formula1: str, title: str, error: str) -> DataValidation:
    return DataValidation(
        type="list",
        formula1=formula1,
        allow_blank=True,
        showDropDown=False,
        showErrorMessage=True,
        showInputMessage=True,
        errorStyle="stop",
        errorTitle=title,
        error=error,
        promptTitle=title,
        prompt="Use the dropdown only.",
    )


def _generation_tokens() -> list[str]:
    return [name.value for name in AttributeName]


def _status_formula(row: int, *, gen_last: int, map_last_row: int) -> str:
    """Validate one marketplace mapping row.

    A=column_index, B=marketplace_column, C=fill_mode, D=pim, E=gen, F=constant.
    Nested IF only (no IFS). Empty / unused rows (A blank or 0 and no fill_mode)
    stay blank.
    """
    a, b, c, d, e, f = (
        f"A{row}",
        f"B{row}",
        f"C{row}",
        f"D{row}",
        f"E{row}",
        f"F{row}",
    )
    fill = "'lists'!$A$2:$A$8"
    pim = f"'pim_contract'!$A$2:$A${PIM_ROWS}"
    gen = f"'lists'!$C$2:$C${gen_last}"
    optional_pim_ok = f'AND({e}="",{f}="",OR({d}="",COUNTIF({pim},{d})>0))'
    return (
        f'=IF(AND(OR({a}="",{a}=0),{c}=""),"",'
        f'IF(OR({a}="",{a}=0),"ERROR: column_index required",'
        f'IF({b}="","ERROR: marketplace_column required",'
        f'IF(COUNTIF($A$2:$A${map_last_row},{a})>1,"ERROR: duplicate column_index",'
        f'IF({c}="","ERROR: fill_mode required",'
        f'IF(COUNTIF({fill},{c})=0,"ERROR: invalid fill_mode",'
        f'IF({c}="COPY_PIM",'
        f'IF(AND({d}<>"",COUNTIF({pim},{d})>0,{e}="",{f}=""),'
        f'"OK","ERROR: COPY_PIM needs pim_field only"),'
        f'IF({c}="ENUM",'
        f'IF({optional_pim_ok},"OK","ERROR: ENUM pim optional; gen/const blank"),'
        f'IF({c}="AI_TEXT",'
        f'IF({optional_pim_ok},"OK","ERROR: AI_TEXT pim optional; gen/const blank"),'
        f'IF({c}="COPY_GENERATION",'
        f'IF(AND({e}<>"",COUNTIF({gen},{e})>0,{d}="",{f}=""),'
        f'"OK","ERROR: COPY_GENERATION needs generation only"),'
        f'IF({c}="IMAGE",'
        f'IF(AND({e}<>"",COUNTIF({gen},{e})>0,{d}="",{f}=""),'
        f'"OK","ERROR: IMAGE needs generation only"),'
        f'IF({c}="CONSTANT",'
        f'IF(AND({f}<>"",{d}="",{e}=""),'
        f'"OK","ERROR: CONSTANT needs constant_value only"),'
        f'IF({c}="SKIP",'
        f'IF(AND({d}="",{e}="",{f}=""),'
        f'"OK","ERROR: SKIP must leave pim/gen/const blank"),'
        f'"ERROR: unhandled fill_mode"'
        f")))))))))))))"
    )


def _readme_blocks() -> list[tuple[str, str]]:
    return [
        ("Listing mapping — how to fill this workbook", "title"),
        ("", "body"),
        (
            (
                "Example rows on amazon_mapping / flipkart_mapping / myntra_mapping are "
                "samples only. Replace them with real column_index + header names from "
                "the blank marketplace workbook for your category."
            ),
            "body",
        ),
        ("", "body"),
        ("Sheets", "section"),
        (
            "pim_contract — customer fields (Mandatory / Optional). Shared by all marketplaces.",
            "body",
        ),
        (
            (
                "amazon_mapping / flipkart_mapping / myntra_mapping — one sheet per marketplace. "
                "Each row is one column from that marketplace’s blank workbook."
            ),
            "body",
        ),
        (
            "lists — dropdown values for fill_mode and generation. Leave alone.",
            "body",
        ),
        ("", "body"),
        ("How to fill a marketplace sheet", "section"),
        (
            "1. Put customer fields on pim_contract first (only what you will ask for).",
            "body",
        ),
        (
            (
                "2. For each blank-workbook column: set column_index, marketplace_column, "
                "and fill_mode. Every row with a column_index needs an explicit fill_mode "
                "(use SKIP if you intentionally leave it blank)."
            ),
            "body",
        ),
        (
            "3. status must be OK (green) on every filled row before you hand this off.",
            "body",
        ),
        (
            (
                "column_index is the Excel column number from the blank template "
                "(unique per marketplace sheet)."
            ),
            "body",
        ),
        ("", "body"),
        ("Which columns to set for each fill_mode", "section"),
        (
            (
                "COPY_PIM — copy a customer field as-is (not a marketplace dropdown). "
                "Set pim_field only."
            ),
            "body",
        ),
        (
            (
                "ENUM — marketplace dropdown. Writes only from the allowed list. "
                "pim_field is optional: set it when there is a related customer field; "
                "leave it blank when there is not."
            ),
            "body",
        ),
        (
            (
                "AI_TEXT — free-text marketplace field (not a dropdown). "
                "pim_field is optional: set it to prefer that customer value when present; "
                "leave it blank to always generate text."
            ),
            "body",
        ),
        (
            (
                "COPY_GENERATION — copy an already-generated value "
                "(title, bullets, description, keywords). Set generation only "
                "(pick from the dropdown; repeat the same name on each matching column)."
            ),
            "body",
        ),
        (
            (
                "IMAGE — generated image URL. Set generation to IMAGE "
                "(repeat on each image column)."
            ),
            "body",
        ),
        ("CONSTANT — fixed string. Set constant_value only.", "body"),
        (
            "SKIP — leave blank. Leave pim_field, generation, and constant_value empty.",
            "body",
        ),
        ("", "body"),
        ("Quick rules", "section"),
        (
            (
                "• For ENUM and AI_TEXT, pim_field is optional. "
                "For every other mode, follow the column rules above."
            ),
            "body",
        ),
        (
            "• When you do set pim_field, it must already exist on pim_contract.",
            "body",
        ),
        (
            (
                "• Leave unused input columns empty "
                "(do not mix modes — e.g. COPY_PIM must not also set generation)."
            ),
            "body",
        ),
        ("• Keep pim_contract small — only fields the customer will fill.", "body"),
        ("", "body"),
        ("Open this file in Microsoft Excel Desktop (File → Open).", "body"),
    ]


def _default_pim_rows() -> list[tuple[str, str]]:
    return [
        ("SKU", "Mandatory"),
        ("Brand", "Mandatory"),
        ("Color", "Mandatory"),
        ("Size", "Optional"),
    ]


# One row per fill_mode, plus a second IMAGE / ITEM_HIGHLIGHTS / BULLET_POINTS
# so the template shows repeating the same generation name. ENUM and AI_TEXT each
# appear twice (with and without pim_field).
_EXAMPLE_FILLS: tuple[tuple[str, str, str, str], ...] = (
    ("COPY_PIM", "SKU", "", ""),
    ("CONSTANT", "", "", "EXAMPLE"),
    ("ENUM", "", "", ""),
    ("ENUM", "Brand", "", ""),
    ("SKIP", "", "", ""),
    ("COPY_GENERATION", "", "TITLE", ""),
    ("COPY_GENERATION", "", "ITEM_HIGHLIGHTS", ""),
    ("COPY_GENERATION", "", "ITEM_HIGHLIGHTS", ""),
    ("IMAGE", "", "IMAGE", ""),
    ("IMAGE", "", "IMAGE", ""),
    ("COPY_GENERATION", "", "DESCRIPTION", ""),
    ("COPY_GENERATION", "", "BULLET_POINTS", ""),
    ("COPY_GENERATION", "", "BULLET_POINTS", ""),
    ("COPY_GENERATION", "", "BACKEND_KEYWORDS", ""),
    ("AI_TEXT", "", "", ""),
    ("AI_TEXT", "Color", "", ""),
)


def _example_mapping_rows(
    headers: tuple[str, ...],
) -> list[tuple[int, str, str, str, str, str]]:
    if len(headers) != len(_EXAMPLE_FILLS):
        raise ValueError("example header count must match _EXAMPLE_FILLS")
    return [
        (index, header, mode, pim, gen, const)
        for index, (header, (mode, pim, gen, const)) in enumerate(
            zip(headers, _EXAMPLE_FILLS, strict=True),
            start=1,
        )
    ]


def _example_amazon_rows() -> list[tuple[int, str, str, str, str, str]]:
    return _example_mapping_rows(
        (
            "SKU",
            "Product Type",
            "Parentage Level",
            "Brand Name",
            "Unused column",
            "Item Name",
            "Item Highlight",
            "Item Highlight",
            "Main Image URL",
            "Other Image URL",
            "Product Description",
            "Bullet Point",
            "Bullet Point",
            "Generic Keyword",
            "Item Type Name",
            "Fabric Type",
        )
    )


def _example_flipkart_rows() -> list[tuple[int, str, str, str, str, str]]:
    return _example_mapping_rows(
        (
            "Seller SKU ID",
            "Listing Status",
            "Country Of Origin",
            "Brand",
            "Flipkart Serial Number",
            "Title",
            "Item Highlight",
            "Item Highlight",
            "Main Image URL",
            "Other Image URL 1",
            "Description",
            "Bullet Point",
            "Bullet Point",
            "Search Keywords",
            "Items Included",
            "Fabric Detail",
        )
    )


def _example_myntra_rows() -> list[tuple[int, str, str, str, str, str]]:
    return _example_mapping_rows(
        (
            "SKU Code",
            "Article Type",
            "Gender",
            "Brand",
            "Unused column",
            "Product Name",
            "Highlight",
            "Highlight",
            "Style Image",
            "Other Image",
            "Description",
            "Bullet",
            "Bullet",
            "Keywords",
            "Care Instructions",
            "Fabric",
        )
    )


def _validate_mapping_rows(
    *,
    marketplace_id: str,
    rows: list[tuple[int, str, str, str, str, str]],
) -> None:
    if len(rows) > MKT_ROWS - 1:
        raise ValueError(
            f"{marketplace_id} mapping has {len(rows)} rows; raise MKT_ROWS "
            f"(currently {MKT_ROWS})"
        )
    indices = [row[0] for row in rows]
    if len(set(indices)) != len(indices):
        raise ValueError(f"{marketplace_id} mapping has duplicate column_index values")
    for idx, name, mode, *_rest in rows:
        if idx < 1:
            raise ValueError(f"{marketplace_id} column_index must be >= 1, got {idx}")
        if not str(name).strip():
            raise ValueError(
                f"{marketplace_id} column_index={idx}: marketplace_column is empty"
            )
        if not str(mode).strip():
            raise ValueError(
                f"{marketplace_id} column_index={idx}: fill_mode required (no silent SKIP)"
            )


def _add_mapping_sheet(
    wb: Workbook,
    *,
    sheet_name: str,
    rows: list[tuple[int, str, str, str, str, str]],
    gen_last: int,
    r_fill: str,
    r_pim: str,
    r_gen: str,
) -> None:
    ws = wb.create_sheet(sheet_name)
    headers = [
        "column_index",
        "marketplace_column",
        "fill_mode",
        "pim_field",
        "generation",
        "constant_value",
        "status",
    ]
    for i, header in enumerate(headers, start=1):
        ws.cell(1, i, header)

    map_last_row = MKT_ROWS
    ordered = list(rows)
    for r in range(2, map_last_row + 1):
        status = ws.cell(r, 7)
        status.value = _status_formula(r, gen_last=gen_last, map_last_row=map_last_row)
        offset = r - 2
        if offset < len(ordered):
            idx, name, mode, pim, gen, const = ordered[offset]
            _set(ws, r, 1, idx)
            _set(ws, r, 2, name)
            _set(ws, r, 3, mode)
            _set(ws, r, 4, pim)
            _set(ws, r, 5, gen)
            _set(ws, r, 6, const)
            ws.cell(r, 7).border = THIN

    _style_header(ws, 7)
    _autosize(ws, [14, 28, 18, 14, 22, 16, 55])

    for dv, rng in (
        (_list_dv(r_fill, "fill_mode", "Pick fill_mode only."), f"C2:C{map_last_row}"),
        (
            _list_dv(r_pim, "pim_field", "Pick from pim_contract only."),
            f"D2:D{map_last_row}",
        ),
        (
            _list_dv(r_gen, "generation", "Pick generation token only."),
            f"E2:E{map_last_row}",
        ),
    ):
        ws.add_data_validation(dv)
        dv.add(rng)

    ws.conditional_formatting.add(
        f"G2:G{map_last_row}",
        FormulaRule(formula=['LEFT(G2,5)="ERROR"'], fill=ERR_FILL, font=ERR_FONT),
    )
    ws.conditional_formatting.add(
        f"G2:G{map_last_row}",
        FormulaRule(formula=['G2="OK"'], fill=OK_FILL),
    )


def build(
    *,
    out_xlsx: Path | None = None,
    pim_rows: list[tuple[str, str]] | None = None,
    marketplace_maps: dict[str, list[tuple[int, str, str, str, str, str]]]
    | None = None,
) -> Path:
    generations = _generation_tokens()
    fill_modes = [
        "COPY_PIM",
        "COPY_GENERATION",
        "ENUM",
        "AI_TEXT",
        "CONSTANT",
        "IMAGE",
        "SKIP",
    ]
    requirements = ["Mandatory", "Optional"]
    gen_last = 1 + len(generations)
    pim_rows = list(pim_rows) if pim_rows is not None else _default_pim_rows()
    allowed_ids = {marketplace_id for marketplace_id, _name in MAPPING_SHEETS}
    maps = {marketplace_id: [] for marketplace_id, _name in MAPPING_SHEETS}
    if marketplace_maps is None:
        maps["AMAZON"] = _example_amazon_rows()
        maps["FLIPKART"] = _example_flipkart_rows()
        maps["MYNTRA"] = _example_myntra_rows()
    else:
        unknown = sorted(set(marketplace_maps) - allowed_ids)
        if unknown:
            raise ValueError(f"Unknown marketplace mapping keys: {unknown}")
        for marketplace_id, rows in marketplace_maps.items():
            maps[marketplace_id] = list(rows)
    for marketplace_id, rows in maps.items():
        _validate_mapping_rows(marketplace_id=marketplace_id, rows=rows)

    out_xlsx = out_xlsx or OUT_XLSX

    wb = Workbook()

    ws_readme = wb.active
    ws_readme.title = "README"
    ws_readme.sheet_properties.tabColor = "1F4E79"
    for i, (text, kind) in enumerate(_readme_blocks(), start=1):
        cell = ws_readme.cell(i, 1)
        if text:
            cell.value = text
            cell.font = (
                TITLE_FONT
                if kind == "title"
                else SECTION_FONT
                if kind == "section"
                else BODY_FONT
            )
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws_readme.column_dimensions["A"].width = 112

    ws_lists = wb.create_sheet("lists")
    ws_lists["A1"] = "fill_mode"
    ws_lists["B1"] = "requirement"
    ws_lists["C1"] = "generation"
    for i, value in enumerate(fill_modes, start=2):
        ws_lists.cell(i, 1, value)
    for i, value in enumerate(requirements, start=2):
        ws_lists.cell(i, 2, value)
    for i, value in enumerate(generations, start=2):
        ws_lists.cell(i, 3, value)
    _style_header(ws_lists, 3)
    _autosize(ws_lists, [18, 14, 22])
    ws_lists.sheet_properties.tabColor = "808080"

    r_fill = "'lists'!$A$2:$A$8"
    r_req = "'lists'!$B$2:$B$3"
    r_gen = f"'lists'!$C$2:$C${gen_last}"
    r_pim = f"'pim_contract'!$A$2:$A${PIM_ROWS}"

    # pim_contract
    ws_pim = wb.create_sheet("pim_contract")
    pim_headers = ["pim_field", "requirement"]
    for i, header in enumerate(pim_headers, start=1):
        ws_pim.cell(1, i, header)
    for r, row in enumerate(pim_rows, start=2):
        _set(ws_pim, r, 1, row[0])
        _set(ws_pim, r, 2, row[1])
    for r in range(len(pim_rows) + 2, PIM_ROWS + 1):
        _set(ws_pim, r, 1, None)
        _set(ws_pim, r, 2, None)
    _style_header(ws_pim, 2)
    _autosize(ws_pim, [24, 14])
    dv_req = _list_dv(r_req, "requirement", "Pick Mandatory or Optional.")
    ws_pim.add_data_validation(dv_req)
    dv_req.add(f"B2:B{PIM_ROWS}")

    for marketplace_id, sheet_name in MAPPING_SHEETS:
        _add_mapping_sheet(
            wb,
            sheet_name=sheet_name,
            rows=maps[marketplace_id],
            gen_last=gen_last,
            r_fill=r_fill,
            r_pim=r_pim,
            r_gen=r_gen,
        )

    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_xlsx)
    return out_xlsx


if __name__ == "__main__":
    path = build()
    print(f"Wrote {path}")
