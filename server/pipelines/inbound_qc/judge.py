"""Text judge: catalog vs photo extract / title. No images, no family thesaurus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from pipelines.inbound_qc.category import (
    CATEGORY_BEDSHEET,
    CATEGORY_GENERIC,
    detect_category,
    is_placeholder,
)
from pipelines.inbound_qc.columns import column_for_visual_field, long_text_columns
from pipelines.inbound_qc.tools import INBOUND_QC_JUDGE_TOOL
from pipelines.inbound_qc.types import (
    CONFLICT_TYPE_LABELS,
    Checklist,
    ExtractField,
    ExtractResult,
    Finding,
    FindingKind,
    SkuBundle,
    Visibility,
    conflict_is_priority,
    format_type_scores,
)

_INFERRED_MIN_CONFIDENCE = 70
_JUDGE_MAX_TOKENS = 1500
_LONG_TEXT_LIMIT = 500
_OBS_LIMIT = 120
_ANALYSIS_LIMIT = 160
_BED_SIZE_LARGE = ("double", "queen", "king", "full")
_BED_SIZE_SMALL = ("single", "twin")
_NON_SHEET_TYPES = (
    "duvet cover",
    "comforter",
    "duvet",
    "quilt",
    "blanket",
    "doona",
)
_SHEET_TYPES = ("bedsheet", "bed sheet", "flat sheet", "fitted sheet")


@dataclass(frozen=True, slots=True)
class JudgePair:
    pair_id: str
    kind: FindingKind
    field: str
    catalog_value: str
    observed: str
    visibility: Visibility = "n/a"
    image_files: str = ""


def _clip(text: object, limit: int) -> str:
    return str(text or "").strip()[:limit]


def _bed_size_bucket(text: str) -> str | None:
    key = text.casefold()
    if any(token in key for token in _BED_SIZE_SMALL):
        return "small"
    if any(token in key for token in _BED_SIZE_LARGE):
        return "large"
    return None


def bedsheet_sizes_are_similar(catalog: str, observed: str) -> bool:
    """Double / Queen / King are the same family; Single is not."""
    left = _bed_size_bucket(catalog)
    right = _bed_size_bucket(observed)
    return left is not None and left == right


def observed_is_not_bedsheet(text: str) -> bool:
    """True when extract named a filled covering instead of a sheet."""
    key = text.casefold()
    has_non_sheet = any(token in key for token in _NON_SHEET_TYPES)
    has_sheet = any(token in key for token in _SHEET_TYPES)
    return has_non_sheet and not has_sheet


def _product_type_field(extract: ExtractResult) -> ExtractField | None:
    field = next((item for item in extract.fields if item.name == "product_type"), None)
    if field is None or not _usable(field):
        return None
    observed = (field.observed or field.family).strip()
    if not observed or not observed_is_not_bedsheet(observed):
        return None
    return field


def _usable(field: ExtractField) -> bool:
    if field.name.lower() == "ocr":
        return False
    if field.visibility == "not_visible":
        return False
    min_inferred = 40 if field.name == "size" else _INFERRED_MIN_CONFIDENCE
    inferred_too_weak = field.visibility == "inferred" and field.confidence < min_inferred
    return not inferred_too_weak


def _image_files(field: ExtractField, bundle: SkuBundle) -> str:
    names = field.images or tuple(image.filename for image in bundle.images)
    return ";".join(names)


def _catalog_value(bundle: SkuBundle, column: str | None) -> str:
    if not column:
        return ""
    value = (bundle.attributes.get(column) or "").strip()
    return "" if is_placeholder(value) else value


def _long_text_blob(bundle: SkuBundle) -> str:
    parts: list[str] = []
    for name in long_text_columns(list(bundle.attributes)):
        value = (bundle.attributes.get(name) or "").strip()
        if value and not is_placeholder(value):
            parts.append(f"{name}: {value[:_LONG_TEXT_LIMIT]}")
    return "\n".join(parts)


def structural_findings(bundle: SkuBundle, extract: ExtractResult) -> list[Finding]:
    """Extract flags that do not need a judge (mixed variants, duvet vs bedsheet)."""
    findings: list[Finding] = []
    if not extract.images_agree and len(bundle.images) > 1:
        findings.append(
            Finding(
                sku_id=bundle.sku_id,
                severity="blocker",
                kind="intra_folder",
                field="images",
                catalog_value="",
                observed="photos look like different variants",
                observation_1="This SKU folder",
                observation_2="Photos look like different product variants",
                notes="Mixed variants, not the same product.",
                confidence=100,
                similarity=0,
                image_files=";".join(image.filename for image in bundle.images),
            )
        )
    findings.extend(_product_type_mismatch_findings(bundle, extract))
    return findings


def _product_type_mismatch_findings(bundle: SkuBundle, extract: ExtractResult) -> list[Finding]:
    if detect_category(list(bundle.attributes), bundle.attributes) != CATEGORY_BEDSHEET:
        return []
    field = _product_type_field(extract)
    if field is None:
        return []
    observed = (field.observed or field.family).strip()
    headers = list(bundle.attributes)
    column = column_for_visual_field(headers, "product_type") or "product_type"
    catalog = _catalog_value(bundle, column) or "bedsheet"
    board = format_type_scores(extract.product_type_scores)
    notes = "Photos look like a filled covering, not a bedsheet."
    if board:
        notes = f"{notes} Scores: {board}."
    return [
        Finding(
            sku_id=bundle.sku_id,
            severity="warning",
            kind="cross_modal",
            field=column,
            catalog_value=catalog,
            observed=observed,
            visibility=field.visibility,
            confidence=field.confidence,
            similarity=10,
            image_files=_image_files(field, bundle),
            observation_1=f"catalog {column}: {catalog}",
            observation_2=f"photos: {observed}",
            notes=notes,
        )
    ]


def build_judge_pairs(
    bundle: SkuBundle,
    checklist: Checklist,
    extract: ExtractResult | None,
) -> list[JudgePair]:
    headers = list(bundle.attributes)
    pairs: list[JudgePair] = []
    long_blob = _long_text_blob(bundle)

    for visual in checklist.visual:
        if visual in {"item_count", "ocr"}:
            continue
        column = column_for_visual_field(headers, visual)
        catalog = _catalog_value(bundle, column)
        if visual == "product_type" and not catalog and checklist.category == CATEGORY_BEDSHEET:
            catalog = "bedsheet"
            column = column or "product_type"
        if not catalog or not column:
            continue
        if long_blob:
            pairs.append(
                JudgePair(
                    pair_id=f"ir:{visual}",
                    kind="intra_row",
                    field=column,
                    catalog_value=catalog,
                    observed=long_blob,
                )
            )

    if extract is None:
        return pairs

    by_name = {field.name: field for field in extract.fields}
    all_files = ";".join(image.filename for image in bundle.images)
    for visual in checklist.visual:
        if visual == "ocr":
            continue
        if visual == "item_count" and checklist.category == CATEGORY_BEDSHEET:
            continue
        if visual == "product_type" and _product_type_field(extract) is not None:
            continue
        column = column_for_visual_field(headers, visual)
        catalog = _catalog_value(bundle, column)
        if visual == "product_type" and not catalog and checklist.category == CATEGORY_BEDSHEET:
            catalog = "bedsheet"
            column = column or "product_type"
        if not catalog or not column:
            continue
        if visual == "item_count":
            total = extract.item_counts.total_visible
            if total is None:
                continue
            pairs.append(
                JudgePair(
                    pair_id="cm:item_count",
                    kind="cross_modal",
                    field=column,
                    catalog_value=catalog,
                    observed=str(total),
                    visibility="clear",
                    image_files=all_files,
                )
            )
            continue
        field = by_name.get(visual)
        if field is None or not _usable(field):
            continue
        observed = (field.observed or field.family).strip()
        if not observed or is_placeholder(observed):
            continue
        if (
            checklist.category == CATEGORY_BEDSHEET
            and visual == "size"
            and bedsheet_sizes_are_similar(catalog, observed)
        ):
            continue
        pairs.append(
            JudgePair(
                pair_id=f"cm:{visual}",
                kind="cross_modal",
                field=column,
                catalog_value=catalog,
                observed=observed,
                visibility=field.visibility,
                image_files=_image_files(field, bundle),
            )
        )
    return pairs


def _pair_lines(pairs: list[JudgePair]) -> list[str]:
    return [
        f"- id={pair.pair_id} type={CONFLICT_TYPE_LABELS.get(pair.kind, pair.kind)} "
        f"field={pair.field} catalog={pair.catalog_value!r} other={pair.observed!r}"
        for pair in pairs
    ]


def _shared_judge_rules() -> list[str]:
    type_hint = ", ".join(
        f"{kind}={label}" for kind, label in CONFLICT_TYPE_LABELS.items() if kind != "error"
    )
    return [
        "You are catalog intake QA. Compare two texts about the same SKU.",
        "Do not pick a winner. Do not use OCR or on-image printed codes.",
        "Ignore TBD and empty values (those pairs are not sent).",
        "Omit true synonyms, omissions, and low-severity disagreements.",
        "Each conflict the reviewer sees has this shape, nothing else:",
        f"1. type — already implied by the pair id ({type_hint}).",
        "2. observation_1 — where it happened + what it is (short).",
        "3. observation_2 — where it happened + what it is (short).",
        "4. analysis — one short sentence. No extra context.",
        "Also set severity: low (drop), medium, or high.",
        "Score two independent axes; do not rank priority:",
        "- certainty 0-100: how sure this is a real contradiction.",
        "- similarity 0-100: how close the two values are.",
        "Calibrate: White vs Green → high, certainty 90-100, similarity 0-20.",
        "UK 8 vs UK 10 → high, certainty 90-100, similarity 10-30.",
        "Yellow vs dusty yellow → low (omit). Navy vs Blue → omit.",
        "Compatible marketing wording is not a conflict.",
        "A pack/count conflict only if the catalog number cannot mean what is shown.",
    ]


def _generic_judge_prompt(pairs: list[JudgePair]) -> str:
    return "\n".join([*_shared_judge_rules(), "Pairs:", *_pair_lines(pairs)])


def _bedsheet_judge_prompt(pairs: list[JudgePair]) -> str:
    extra = [
        "This catalog row is listed as a bedsheet.",
        "Double, Queen, and King are the same size family. Omit those size pairs.",
        "Single vs Double/Queen/King is a real size mismatch if you are certain.",
        "Omit product_type only when both sides are bedsheet, flat sheet, fitted sheet, "
        "or bedsheet set.",
        "Catalog bedsheet vs photo duvet, comforter, quilt, blanket, or duvet cover is a "
        "product-type mismatch. Do not omit. High certainty, low similarity.",
        "Return only priority conflicts for colour and size: high certainty and clearly "
        "different values.",
        "Mark shade differences, near-matches, and unsure cases as severity low.",
    ]
    return "\n".join([*_shared_judge_rules(), *extra, "Pairs:", *_pair_lines(pairs)])


def judge_prompt(pairs: list[JudgePair], category: str = CATEGORY_GENERIC) -> str:
    """Text-only conflict scoring. Bedsheet rules when category is bedsheet."""
    if category == CATEGORY_BEDSHEET:
        return _bedsheet_judge_prompt(pairs)
    return _generic_judge_prompt(pairs)


def _score(raw: Any) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return max(0, min(100, int(round(float(raw)))))


def parse_judge_payload(
    parsed: dict[str, Any],
    pairs: list[JudgePair],
    sku_id: str,
    *,
    category: str = CATEGORY_GENERIC,
) -> list[Finding]:
    by_id = {pair.pair_id: pair for pair in pairs}
    raw = parsed.get("conflicts")
    if not isinstance(raw, list):
        return []
    findings: list[Finding] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        pair_id = str(item.get("pair_id") or "").strip()
        if not pair_id or pair_id in seen:
            continue
        pair = by_id.get(pair_id)
        if pair is None:
            continue
        seen.add(pair_id)
        judge_severity = str(item.get("severity") or "").strip().lower()
        if judge_severity == "low":
            continue
        certainty = _score(item.get("certainty"))
        similarity = _score(item.get("similarity"))
        product_type_pair = pair.pair_id == "cm:product_type"
        if (
            category == CATEGORY_BEDSHEET
            and not product_type_pair
            and not conflict_is_priority(certainty, similarity)
        ):
            continue
        observation_1 = _clip(item.get("observation_1"), _OBS_LIMIT)
        observation_2 = _clip(item.get("observation_2"), _OBS_LIMIT)
        analysis = _clip(item.get("analysis") or item.get("note"), _ANALYSIS_LIMIT)
        findings.append(
            Finding(
                sku_id=sku_id,
                severity="warning",
                kind=pair.kind,
                field=pair.field,
                catalog_value=observation_1 or _clip(pair.catalog_value, _OBS_LIMIT),
                observed=observation_2 or _clip(pair.observed, _OBS_LIMIT),
                visibility=pair.visibility,
                confidence=certainty,
                similarity=similarity,
                image_files=pair.image_files,
                observation_1=observation_1,
                observation_2=observation_2,
                notes=analysis or "judge: conflict",
            )
        )
    return findings


def judge_pairs(
    client: OpenRouterClient,
    pairs: list[JudgePair],
    *,
    model: str,
    sku_id: str,
    category: str = CATEGORY_GENERIC,
) -> list[Finding]:
    if not pairs:
        return []
    parsed = client.call_tool(
        judge_prompt(pairs, category=category),
        model=model,
        tool=INBOUND_QC_JUDGE_TOOL,
        max_tokens=_JUDGE_MAX_TOKENS,
    )
    if not isinstance(parsed, dict):
        raise ValueError("inbound QC judge returned a non-object")
    return parse_judge_payload(parsed, pairs, sku_id, category=category)
