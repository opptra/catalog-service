"""Parse category ↔ marketplace listing mapping CSV.

Expected columns:
  - Flat Field Name — PIM / ingest header our system understands
  - Requirement — Mandatory | Optional (feeds categories.attribute_spec)
  - AI_GENERATED — true/false (free-text or ENUM-without-source vs DIRECT_MAP/ENUM+source)
  - One marketplace column whose *header* is the marketplace name (e.g. Amazon);
    cell values are template column labels / machine keys

Does not write to any database.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

_FLAT_FIELD_ALIASES = frozenset(
    {
        "flat field name",
        "flat_field_name",
        "flatfieldname",
        "field name",
        "field_name",
    }
)
_REQUIREMENT_ALIASES = frozenset(
    {
        "requirement",
        "requiredness",
        "required",
    }
)
_AI_GENERATED_ALIASES = frozenset(
    {
        "ai_generated",
        "ai generated",
        "aigenerated",
        "ai",
    }
)
_KNOWN_ALIASES = _FLAT_FIELD_ALIASES | _REQUIREMENT_ALIASES | _AI_GENERATED_ALIASES

_MANDATORY_VALUES = frozenset({"mandatory", "required", "always", "true", "yes", "1"})
_OPTIONAL_VALUES = frozenset({"optional", "false", "no", "0", ""})
_TRUE_VALUES = frozenset({"true", "yes", "1", "y", "t"})
_FALSE_VALUES = frozenset({"false", "no", "0", "n", "f", ""})


@dataclass(frozen=True)
class MappingRow:
    flat_field_name: str
    mandatory: bool
    marketplace_column: str | None
    ai_generated: bool


@dataclass(frozen=True)
class MappingCsv:
    marketplace_header: str
    rows: list[MappingRow]


def _norm_header(raw: str) -> str:
    return " ".join(raw.strip().casefold().replace("_", " ").split())


def _parse_bool(raw: str, *, field: str) -> bool:
    needle = raw.strip().casefold()
    if needle in _TRUE_VALUES:
        return True
    if needle in _FALSE_VALUES:
        return False
    raise ValueError(f"Invalid {field} value: {raw!r} (expected true/false)")


def _parse_mandatory(raw: str) -> bool:
    needle = raw.strip().casefold()
    if needle in _MANDATORY_VALUES:
        return True
    if needle in _OPTIONAL_VALUES:
        return False
    raise ValueError(f"Invalid Requirement value: {raw!r} (expected Mandatory/Optional)")


def _resolve_headers(fieldnames: list[str]) -> tuple[str, str, str, str]:
    """Return (flat_field, requirement, ai_generated, marketplace) original headers."""
    by_norm: dict[str, str] = {}
    for name in fieldnames:
        if name is None or not str(name).strip():
            continue
        original = str(name).strip()
        key = _norm_header(original)
        if key in by_norm:
            raise ValueError(f"Duplicate CSV header: {original!r}")
        by_norm[key] = original

    flat_key = next((k for k in by_norm if k in _FLAT_FIELD_ALIASES), None)
    req_key = next((k for k in by_norm if k in _REQUIREMENT_ALIASES), None)
    ai_key = next((k for k in by_norm if k in _AI_GENERATED_ALIASES), None)
    if flat_key is None:
        raise ValueError("CSV missing Flat Field Name column")
    if req_key is None:
        raise ValueError("CSV missing Requirement column")
    if ai_key is None:
        raise ValueError("CSV missing AI_GENERATED column")

    marketplace_keys = [k for k in by_norm if k not in _KNOWN_ALIASES]
    if len(marketplace_keys) == 0:
        raise ValueError("CSV missing marketplace column (header should be the marketplace name)")
    if len(marketplace_keys) > 1:
        names = [by_norm[k] for k in marketplace_keys]
        raise ValueError(f"CSV has multiple marketplace columns {names}; expected exactly one")
    return (
        by_norm[flat_key],
        by_norm[req_key],
        by_norm[ai_key],
        by_norm[marketplace_keys[0]],
    )


def parse_mapping_csv(path: Path) -> MappingCsv:
    text = path.read_text(encoding="utf-8-sig")
    return parse_mapping_csv_text(text)


def parse_mapping_csv_text(text: str) -> MappingCsv:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("Mapping CSV has no header row")
    flat_h, req_h, ai_h, mkt_h = _resolve_headers(list(reader.fieldnames))

    rows: list[MappingRow] = []
    seen_fields: set[str] = set()
    seen_marketplace: dict[str, str] = {}

    for index, raw in enumerate(reader, start=2):
        flat = (raw.get(flat_h) or "").strip()
        if not flat:
            # Skip fully empty trailing rows.
            if not any((raw.get(h) or "").strip() for h in (req_h, ai_h, mkt_h)):
                continue
            raise ValueError(f"Row {index}: Flat Field Name is empty")
        if flat in seen_fields:
            raise ValueError(f"Row {index}: duplicate Flat Field Name {flat!r}")
        seen_fields.add(flat)

        mandatory = _parse_mandatory(raw.get(req_h) or "")
        ai_generated = _parse_bool(raw.get(ai_h) or "", field="AI_GENERATED")
        marketplace = (raw.get(mkt_h) or "").strip() or None

        if marketplace is not None:
            prior = seen_marketplace.get(marketplace.casefold())
            if prior is not None and prior != flat:
                raise ValueError(
                    f"Row {index}: marketplace column {marketplace!r} already mapped to {prior!r}"
                )
            seen_marketplace[marketplace.casefold()] = flat

        rows.append(
            MappingRow(
                flat_field_name=flat,
                mandatory=mandatory,
                marketplace_column=marketplace,
                ai_generated=ai_generated,
            )
        )

    if not rows:
        raise ValueError("Mapping CSV has no data rows")

    return MappingCsv(marketplace_header=mkt_h, rows=rows)


def build_attribute_spec(rows: list[MappingRow]) -> dict[str, list[str]]:
    """Build categories.attribute_spec from mapping rows (inject SKU if missing)."""
    allowed: list[str] = []
    mandatory: list[str] = []
    seen: set[str] = set()
    for row in rows:
        name = row.flat_field_name
        if name in seen:
            continue
        seen.add(name)
        allowed.append(name)
        if row.mandatory:
            mandatory.append(name)

    if "SKU" not in seen:
        allowed.insert(0, "SKU")
        mandatory.insert(0, "SKU")
    elif "SKU" not in mandatory:
        # Identity is always required for ingest even if CSV marked optional.
        mandatory.insert(0, "SKU")

    return {"allowed": allowed, "mandatory": mandatory}
