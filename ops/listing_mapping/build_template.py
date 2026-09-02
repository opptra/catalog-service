"""Build Excel-only listing mapping template (no Google Sheets concerns).

Writes ``tmp/listing_mapping_template.xlsx``. Avoids empty inlineStr cells and
oversized prefilled formula grids — those trigger Excel's repair dialog.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "server") not in sys.path:
    sys.path.insert(0, str(_REPO / "server"))

from entities.catalog.attribute_enums import AttributeName

OUT_XLSX = _REPO / "tmp" / "listing_mapping_template.xlsx"
OUT_DIR = _REPO / "tmp" / "listing_mapping_template"
OUT_README = _REPO / "tmp" / "listing_mapping_template_README.txt"

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

# Prefill only a modest buffer of editable rows (Excel-friendly).
MAP_ROWS = 80
PIM_ROWS = 80
MKT_ROWS = 120
ARRAY_MAX = 10
SLOT_MAX = 12


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


def _set(ws, row: int, col: int, value: str | None) -> None:
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
    scalar = {
        AttributeName.TITLE,
        AttributeName.DESCRIPTION,
        AttributeName.KEY_FEATURES,
        AttributeName.BACKEND_KEYWORDS,
    }
    array_indexed = {AttributeName.BULLET_POINTS, AttributeName.ITEM_HIGHLIGHTS}
    multi_slot = {AttributeName.IMAGE, AttributeName.A_PLUS}
    tokens: list[str] = []
    for name in AttributeName:
        if name in scalar:
            tokens.append(name.value)
        elif name in array_indexed:
            for i in range(1, ARRAY_MAX + 1):
                tokens.append(f"{name.value}:{i}")
            tokens.append(name.value)
        elif name in multi_slot:
            for i in range(1, SLOT_MAX + 1):
                tokens.append(f"{name.value}:{i}")
        else:
            tokens.append(name.value)
    return tokens


def _status_formula(row: int, *, gen_last: int) -> str:
    """Flat IFS formula — Excel Desktop friendly, no deep nested IF."""
    a, b, c, d, e = f"A{row}", f"B{row}", f"C{row}", f"D{row}", f"E{row}"
    mkt = f"'marketplace_columns'!$A$2:$A${MKT_ROWS}"
    fill = "'lists'!$A$2:$A$9"
    pim = f"'pim_contract'!$A$2:$A${PIM_ROWS}"
    gen = f"'lists'!$C$2:$C${gen_last}"
    return (
        f'=IF(AND({a}="",{b}=""),"",'
        f"IFS("
        f'{a}="","ERROR: marketplace_column required",'
        f'COUNTIF({mkt},{a})=0,"ERROR: marketplace_column not in marketplace_columns",'
        f'{b}="","ERROR: fill_mode required",'
        f'COUNTIF({fill},{b})=0,"ERROR: invalid fill_mode",'
        f'AND({b}="COPY_PIM",{c}<>"",COUNTIF({pim},{c})>0,{d}="",{e}=""),"OK",'
        f'{b}="COPY_PIM","ERROR: COPY_PIM needs pim_field only",'
        f'AND({b}="ENUM_FROM_PIM",{c}<>"",COUNTIF({pim},{c})>0,{d}="",{e}=""),"OK",'
        f'{b}="ENUM_FROM_PIM","ERROR: ENUM_FROM_PIM needs pim_field only",'
        f'AND({b}="COPY_GENERATION",{d}<>"",COUNTIF({gen},{d})>0,{c}="",{e}=""),"OK",'
        f'{b}="COPY_GENERATION","ERROR: COPY_GENERATION needs generation only",'
        f'AND({b}="IMAGE",{d}<>"",COUNTIF({gen},{d})>0,{c}="",{e}=""),"OK",'
        f'{b}="IMAGE","ERROR: IMAGE needs generation only",'
        f'AND({b}="CONSTANT",{e}<>"",{c}="",{d}=""),"OK",'
        f'{b}="CONSTANT","ERROR: CONSTANT needs constant_value only",'
        f'AND(OR({b}="ENUM_AI",{b}="AI_TEXT",{b}="SKIP"),{c}="",{d}="",{e}=""),"OK",'
        f'OR({b}="ENUM_AI",{b}="AI_TEXT",{b}="SKIP"),'
        f'"ERROR: this mode must leave pim/generation/constant blank",'
        f'TRUE,"ERROR: unhandled fill_mode"'
        f"))"
    )


def _readme_blocks() -> list[tuple[str, str]]:
    return [
        ("Listing mapping — how to fill this workbook", "title"),
        ("", "body"),
        ("What each sheet is for", "section"),
        (
            "1. pim_contract — fields we ask the customer (Mandatory / Optional).",
            "body",
        ),
        (
            (
                "2. marketplace_columns — exact Amazon Template labels or machine keys "
                "from the blank .xlsm."
            ),
            "body",
        ),
        (
            "3. listing_map — one row per marketplace column: how it gets filled.",
            "body",
        ),
        (
            "4. lists — dropdown vocabulary only. Do not edit unless you know why.",
            "body",
        ),
        ("", "body"),
        ("Fill order", "section"),
        ("A. Add customer fields on pim_contract.", "body"),
        (
            (
                "B. Paste exact Amazon column names on marketplace_columns "
                "(label or machine_key)."
            ),
            "body",
        ),
        (
            "C. On listing_map, pick marketplace_column + fill_mode from dropdowns.",
            "body",
        ),
        ("D. status must be OK (green). Fix any ERROR row before handoff.", "body"),
        ("", "body"),
        ("When to pick each fill_mode", "section"),
        (
            (
                "COPY_PIM — plain copy of a customer field (not an Amazon dropdown). "
                "Set pim_field only."
            ),
            "body",
        ),
        (
            (
                "COPY_GENERATION — copy an already-generated value "
                "(title, bullets, description, keywords). Set generation only."
            ),
            "body",
        ),
        ("IMAGE — generated image URL. Set generation to IMAGE:n or A_PLUS:n.", "body"),
        (
            (
                "AI_TEXT — free-text Amazon field (not a dropdown) with no PIM twin "
                "and not from generation."
            ),
            "body",
        ),
        ("CONSTANT — fixed string (e.g. Update). Set constant_value only.", "body"),
        ("SKIP — leave blank. Leave pim/generation/constant blank.", "body"),
        ("", "body"),
        ("Amazon dropdowns (ENUM)", "section"),
        (
            (
                "Both ENUM modes write only values from Amazon’s allowed list. "
                "Never free text."
            ),
            "body",
        ),
        ("", "body"),
        (
            "ENUM_FROM_PIM — customer has a related PIM field (set pim_field).",
            "body",
        ),
        (
            (
                "  1) PIM value exact-matches an allowed option (case-insensitive) "
                "→ write that option. No model."
            ),
            "body",
        ),
        (
            (
                "  2) No match → model picks from the allowed list using the full PIM bag "
                "+ product photos (mapped field is a hint). Weak evidence → may stay blank."
            ),
            "body",
        ),
        ("", "body"),
        (
            (
                "ENUM_AI — no dedicated PIM field. Leave pim_field blank. Always model-picks "
                "from the allowed list using the full PIM bag + photos."
            ),
            "body",
        ),
        ("", "body"),
        ("When is the model involved?", "section"),
        (
            (
                "ENUM_FROM_PIM mismatch → model (list-constrained). "
                "ENUM_AI → always model (list-constrained). AI_TEXT → free text. "
                "COPY_* / IMAGE / CONSTANT / SKIP / exact ENUM match → no model."
            ),
            "body",
        ),
        ("", "body"),
        ("generation tokens", "section"),
        (
            "Bare name = whole value: TITLE, DESCRIPTION, KEY_FEATURES, BACKEND_KEYWORDS.",
            "body",
        ),
        ("NAME:n list item: BULLET_POINTS:1 …, ITEM_HIGHLIGHTS:1 …", "body"),
        ("NAME:n image slot: IMAGE:1 …, A_PLUS:1 …", "body"),
        ("", "body"),
        ("Hard rules", "section"),
        (
            "• Dropdowns only for marketplace_column, fill_mode, pim_field, generation.",
            "body",
        ),
        (
            (
                "• marketplace_column / pim_field must exist on their sheets "
                "with exact spelling/case."
            ),
            "body",
        ),
        ("• Keep pim_contract minimal.", "body"),
        ("• status = OK on every filled listing_map row before handoff.", "body"),
        ("", "body"),
        ("Open this file in Microsoft Excel Desktop (File → Open).", "body"),
    ]


def build() -> Path:
    generations = _generation_tokens()
    fill_modes = [
        "COPY_PIM",
        "COPY_GENERATION",
        "ENUM_FROM_PIM",
        "ENUM_AI",
        "AI_TEXT",
        "CONSTANT",
        "IMAGE",
        "SKIP",
    ]
    requirements = ["Mandatory", "Optional"]
    column_sources = ["label", "machine_key"]
    gen_last = 1 + len(generations)

    wb = Workbook()

    # README
    ws_readme = wb.active
    ws_readme.title = "README"
    ws_readme.sheet_properties.tabColor = "1F4E79"
    for i, (text, kind) in enumerate(_readme_blocks(), start=1):
        cell = ws_readme.cell(i, 1)
        # Never write "" — empty inlineStr cells make Excel show the repair dialog.
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

    # lists
    ws_lists = wb.create_sheet("lists")
    ws_lists["A1"] = "fill_mode"
    ws_lists["B1"] = "requirement"
    ws_lists["C1"] = "generation"
    ws_lists["D1"] = "column_source"
    for i, value in enumerate(fill_modes, start=2):
        ws_lists.cell(i, 1, value)
    for i, value in enumerate(requirements, start=2):
        ws_lists.cell(i, 2, value)
    for i, value in enumerate(generations, start=2):
        ws_lists.cell(i, 3, value)
    for i, value in enumerate(column_sources, start=2):
        ws_lists.cell(i, 4, value)
    _style_header(ws_lists, 4)
    _autosize(ws_lists, [18, 14, 22, 14])
    ws_lists.sheet_properties.tabColor = "808080"

    # Quoted sheet refs — required for reliable Excel list validation
    r_fill = "'lists'!$A$2:$A$9"
    r_req = "'lists'!$B$2:$B$3"
    r_gen = f"'lists'!$C$2:$C${gen_last}"
    r_src = "'lists'!$D$2:$D$3"
    r_pim = f"'pim_contract'!$A$2:$A${PIM_ROWS}"
    r_mkt = f"'marketplace_columns'!$A$2:$A${MKT_ROWS}"

    # pim_contract
    ws_pim = wb.create_sheet("pim_contract")
    pim_headers = ["pim_field", "requirement"]
    for i, header in enumerate(pim_headers, start=1):
        ws_pim.cell(1, i, header)
    pim_rows = [
        ("SKU", "Mandatory"),
        ("Color", "Mandatory"),
        ("Size", "Mandatory"),
        ("Material", "Optional"),
        ("Brand", "Mandatory"),
        ("Pattern", "Optional"),
    ]
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

    # marketplace_columns
    ws_mkt = wb.create_sheet("marketplace_columns")
    mkt_headers = ["marketplace_column", "source"]
    for i, header in enumerate(mkt_headers, start=1):
        ws_mkt.cell(1, i, header)
    mkt_rows = [
        ("Seller SKU", "label"),
        ("Brand Name", "label"),
        ("Color", "label"),
        ("Size", "label"),
        ("Material Type", "label"),
        ("Item Name", "label"),
        ("Bullet Point 1", "label"),
        ("Bullet Point 2", "label"),
        ("Bullet Point 3", "label"),
        ("Bullet Point 4", "label"),
        ("Bullet Point 5", "label"),
        ("Generic Keywords", "label"),
        ("Product Description", "label"),
        ("Main Image URL", "label"),
        ("Other Image URL1", "label"),
        ("Other Image URL2", "label"),
        ("Update Delete", "label"),
        ("Product ID", "label"),
        ("League Name", "label"),
        ("Team Name", "label"),
        ("Pattern Name", "label"),
    ]
    for r, row in enumerate(mkt_rows, start=2):
        _set(ws_mkt, r, 1, row[0])
        _set(ws_mkt, r, 2, row[1])
    for r in range(len(mkt_rows) + 2, MKT_ROWS + 1):
        _set(ws_mkt, r, 1, None)
        _set(ws_mkt, r, 2, None)
    _style_header(ws_mkt, 2)
    _autosize(ws_mkt, [28, 14])
    dv_src = _list_dv(r_src, "source", "Pick label or machine_key.")
    ws_mkt.add_data_validation(dv_src)
    dv_src.add(f"B2:B{MKT_ROWS}")

    # listing_map
    ws_map = wb.create_sheet("listing_map")
    map_headers = [
        "marketplace_column",
        "fill_mode",
        "pim_field",
        "generation",
        "constant_value",
        "status",
    ]
    for i, header in enumerate(map_headers, start=1):
        ws_map.cell(1, i, header)

    map_rows = [
        ("Seller SKU", "COPY_PIM", "SKU", "", ""),
        ("Brand Name", "COPY_PIM", "Brand", "", ""),
        ("Color", "ENUM_FROM_PIM", "Color", "", ""),
        ("Size", "ENUM_FROM_PIM", "Size", "", ""),
        ("Material Type", "ENUM_AI", "", "", ""),
        ("Item Name", "COPY_GENERATION", "", "TITLE", ""),
        ("Bullet Point 1", "COPY_GENERATION", "", "BULLET_POINTS:1", ""),
        ("Bullet Point 2", "COPY_GENERATION", "", "BULLET_POINTS:2", ""),
        ("Bullet Point 3", "COPY_GENERATION", "", "BULLET_POINTS:3", ""),
        ("Bullet Point 4", "COPY_GENERATION", "", "BULLET_POINTS:4", ""),
        ("Bullet Point 5", "COPY_GENERATION", "", "BULLET_POINTS:5", ""),
        ("Generic Keywords", "COPY_GENERATION", "", "BACKEND_KEYWORDS", ""),
        ("Product Description", "COPY_GENERATION", "", "DESCRIPTION", ""),
        ("Main Image URL", "IMAGE", "", "IMAGE:1", ""),
        ("Other Image URL1", "IMAGE", "", "IMAGE:2", ""),
        ("Other Image URL2", "IMAGE", "", "IMAGE:3", ""),
        ("Update Delete", "CONSTANT", "", "", "Update"),
        ("Product ID", "SKIP", "", "", ""),
        ("League Name", "ENUM_AI", "", "", ""),
        ("Team Name", "ENUM_AI", "", "", ""),
        ("Pattern Name", "COPY_PIM", "Pattern", "", ""),
    ]

    for r, row in enumerate(map_rows, start=2):
        for c, value in enumerate(row, start=1):
            _set(ws_map, r, c, value)
        status = ws_map.cell(r, 6)
        status.value = _status_formula(r, gen_last=gen_last)
        status.border = THIN

    for r in range(len(map_rows) + 2, MAP_ROWS + 1):
        for c in range(1, 6):
            _set(ws_map, r, c, None)
        status = ws_map.cell(r, 6)
        status.value = _status_formula(r, gen_last=gen_last)
        status.border = THIN

    _style_header(ws_map, 6)
    _autosize(ws_map, [22, 18, 14, 22, 16, 55])

    for dv, rng in (
        (
            _list_dv(
                r_mkt, "marketplace_column", "Pick from marketplace_columns only."
            ),
            f"A2:A{MAP_ROWS}",
        ),
        (_list_dv(r_fill, "fill_mode", "Pick fill_mode only."), f"B2:B{MAP_ROWS}"),
        (
            _list_dv(r_pim, "pim_field", "Pick from pim_contract only."),
            f"C2:C{MAP_ROWS}",
        ),
        (
            _list_dv(r_gen, "generation", "Pick generation token only."),
            f"D2:D{MAP_ROWS}",
        ),
    ):
        ws_map.add_data_validation(dv)
        dv.add(rng)

    ws_map.conditional_formatting.add(
        f"F2:F{MAP_ROWS}",
        FormulaRule(formula=['LEFT(F2,5)="ERROR"'], fill=ERR_FILL, font=ERR_FONT),
    )
    ws_map.conditional_formatting.add(
        f"F2:F{MAP_ROWS}",
        FormulaRule(formula=['F2="OK"'], fill=OK_FILL),
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_XLSX.parent.mkdir(parents=True, exist_ok=True)

    def write_csv(path: Path, headers: list[str], rows: list[tuple]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)

    write_csv(OUT_DIR / "pim_contract.csv", pim_headers, pim_rows)
    write_csv(OUT_DIR / "marketplace_columns.csv", mkt_headers, mkt_rows)
    write_csv(OUT_DIR / "listing_map.csv", map_headers[:-1], map_rows)
    write_csv(OUT_DIR / "generations.csv", ["generation"], [[g] for g in generations])
    OUT_README.write_text(
        "\n".join(text for text, _ in _readme_blocks()) + "\n",
        encoding="utf-8",
    )

    wb.save(OUT_XLSX)
    return OUT_XLSX


if __name__ == "__main__":
    path = build()
    print(f"Wrote {path}")
