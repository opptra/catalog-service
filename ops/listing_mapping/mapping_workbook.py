"""Parse the restricted listing-mapping Excel workbook (tmp template contract).

Sheets:
  - pim_contract: pim_field, requirement
  - listing_map: column_index, fill_mode, pim_field, generation, constant_value
  - marketplace_columns: optional vocabulary (column_index unique key)

``marketplace_column`` on listing_map may be a VLOOKUP formula — ignored at
parse time; matching is by column_index only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet


class FillMode(StrEnum):
    COPY_PIM = "COPY_PIM"
    COPY_GENERATION = "COPY_GENERATION"
    ENUM_FROM_PIM = "ENUM_FROM_PIM"
    ENUM_AI = "ENUM_AI"
    AI_TEXT = "AI_TEXT"
    CONSTANT = "CONSTANT"
    IMAGE = "IMAGE"
    SKIP = "SKIP"


@dataclass(frozen=True)
class PimFieldRow:
    pim_field: str
    mandatory: bool


@dataclass(frozen=True)
class ListingMapRow:
    column_index: int
    fill_mode: FillMode
    pim_field: str | None
    generation: str | None
    constant_value: str | None


@dataclass(frozen=True)
class MappingWorkbook:
    pim_fields: list[PimFieldRow]
    listing_rows: list[ListingMapRow]


_REQ_MANDATORY = frozenset({"mandatory", "required", "always", "true", "yes", "1"})
_REQ_OPTIONAL = frozenset({"optional", "false", "no", "0", ""})


def _cell_str(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith("="):
        # Unevaluated formula (e.g. status / VLOOKUP) — treat as empty for inputs.
        return ""
    return str(value).strip()


def _header_map(ws: Worksheet) -> dict[str, int]:
    headers: dict[str, int] = {}
    for col in range(1, (ws.max_column or 0) + 1):
        raw = ws.cell(1, col).value
        if raw is None or not str(raw).strip():
            continue
        key = " ".join(str(raw).strip().casefold().replace("_", " ").split())
        headers[key] = col
    return headers


def _require_headers(
    headers: dict[str, int],
    needed: dict[str, str],
    *,
    sheet: str,
) -> dict[str, int]:
    """needed: normalized_name → display name for errors."""
    out: dict[str, int] = {}
    for norm, display in needed.items():
        if norm not in headers:
            raise ValueError(f"Sheet {sheet!r} missing required column {display!r}")
        out[norm] = headers[norm]
    return out


def _parse_requirement(raw: str) -> bool:
    needle = raw.casefold()
    if needle in _REQ_MANDATORY:
        return True
    if needle in _REQ_OPTIONAL:
        return False
    raise ValueError(f"Invalid requirement {raw!r} (expected Mandatory/Optional)")


def _parse_pim_contract(ws: Worksheet) -> list[PimFieldRow]:
    headers = _header_map(ws)
    cols = _require_headers(
        headers,
        {"pim field": "pim_field", "requirement": "requirement"},
        sheet="pim_contract",
    )
    rows: list[PimFieldRow] = []
    seen: set[str] = set()
    for r in range(2, (ws.max_row or 1) + 1):
        field = _cell_str(ws.cell(r, cols["pim field"]).value)
        req = _cell_str(ws.cell(r, cols["requirement"]).value)
        if not field and not req:
            continue
        if not field:
            raise ValueError(f"pim_contract row {r}: pim_field is empty")
        if field in seen:
            raise ValueError(f"pim_contract row {r}: duplicate pim_field {field!r}")
        seen.add(field)
        rows.append(PimFieldRow(pim_field=field, mandatory=_parse_requirement(req)))
    if not rows:
        raise ValueError("pim_contract has no data rows")
    return rows


def _parse_listing_map(ws: Worksheet) -> list[ListingMapRow]:
    headers = _header_map(ws)
    cols = _require_headers(
        headers,
        {
            "column index": "column_index",
            "fill mode": "fill_mode",
        },
        sheet="listing_map",
    )
    pim_col = headers.get("pim field")
    gen_col = headers.get("generation")
    const_col = headers.get("constant value")

    rows: list[ListingMapRow] = []
    seen_idx: set[int] = set()
    for r in range(2, (ws.max_row or 1) + 1):
        idx_raw = ws.cell(r, cols["column index"]).value
        mode_raw = _cell_str(ws.cell(r, cols["fill mode"]).value)
        if idx_raw is None or idx_raw == "":
            if not mode_raw:
                continue
            raise ValueError(f"listing_map row {r}: column_index is empty")
        try:
            column_index = int(idx_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"listing_map row {r}: column_index must be an int, got {idx_raw!r}"
            ) from exc
        if column_index < 1:
            raise ValueError(f"listing_map row {r}: column_index must be >= 1")
        if column_index in seen_idx:
            raise ValueError(
                f"listing_map row {r}: duplicate column_index {column_index}"
            )
        seen_idx.add(column_index)
        if not mode_raw:
            raise ValueError(f"listing_map row {r}: fill_mode is empty")
        try:
            fill_mode = FillMode(mode_raw)
        except ValueError as exc:
            known = ", ".join(m.value for m in FillMode)
            raise ValueError(
                f"listing_map row {r}: invalid fill_mode {mode_raw!r}. Expected: {known}"
            ) from exc

        pim = _cell_str(ws.cell(r, pim_col).value) if pim_col else ""
        gen = _cell_str(ws.cell(r, gen_col).value) if gen_col else ""
        const = _cell_str(ws.cell(r, const_col).value) if const_col else ""
        rows.append(
            ListingMapRow(
                column_index=column_index,
                fill_mode=fill_mode,
                pim_field=pim or None,
                generation=gen or None,
                constant_value=const or None,
            )
        )
    if not rows:
        raise ValueError("listing_map has no data rows")
    return rows


def parse_mapping_workbook(path: Path) -> MappingWorkbook:
    if not path.is_file():
        raise FileNotFoundError(f"Mapping workbook not found: {path}")
    # data_only=False so openpyxl-written static cells always load (formulas skipped).
    wb = load_workbook(path, data_only=False, read_only=True)
    try:
        names = {n.casefold(): n for n in wb.sheetnames}
        if "pim_contract" not in names:
            raise ValueError("Mapping workbook missing sheet 'pim_contract'")
        if "listing_map" not in names:
            raise ValueError("Mapping workbook missing sheet 'listing_map'")
        pim = _parse_pim_contract(wb[names["pim_contract"]])
        listing = _parse_listing_map(wb[names["listing_map"]])
    finally:
        wb.close()

    pim_names = {row.pim_field for row in pim}
    for row in listing:
        if row.pim_field and row.pim_field not in pim_names:
            raise ValueError(
                f"listing_map column_index={row.column_index}: pim_field "
                f"{row.pim_field!r} is not on pim_contract"
            )
    return MappingWorkbook(pim_fields=pim, listing_rows=listing)


def build_attribute_spec(pim_fields: list[PimFieldRow]) -> dict[str, list[str]]:
    allowed: list[str] = []
    mandatory: list[str] = []
    seen: set[str] = set()
    for row in pim_fields:
        if row.pim_field in seen:
            continue
        seen.add(row.pim_field)
        allowed.append(row.pim_field)
        if row.mandatory:
            mandatory.append(row.pim_field)
    if "SKU" not in seen:
        allowed.insert(0, "SKU")
        mandatory.insert(0, "SKU")
    elif "SKU" not in mandatory:
        mandatory.insert(0, "SKU")
    return {"allowed": allowed, "mandatory": mandatory}
