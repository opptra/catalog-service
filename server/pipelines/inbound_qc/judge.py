"""Text judge: catalog vs photo extract / title. No images, no family thesaurus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from pipelines.inbound_qc.category import CATEGORY_BEDSHEET, is_placeholder
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
)

_INFERRED_MIN_CONFIDENCE = 70
_JUDGE_MAX_TOKENS = 1500
_LONG_TEXT_LIMIT = 500
_OBS_LIMIT = 120
_ANALYSIS_LIMIT = 160


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
    """Boolean extract flags that do not need a judge (mixed variants)."""
    if extract.images_agree or len(bundle.images) <= 1:
        return []
    return [
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


def judge_prompt(pairs: list[JudgePair]) -> str:
    """Text-only conflict scoring. Type comes from the pair; observations stay short."""
    type_hint = ", ".join(
        f"{kind}={label}" for kind, label in CONFLICT_TYPE_LABELS.items() if kind != "error"
    )
    lines = [
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
        "A bedsheet set is the same product type as catalog bedsheet. Omit that pair.",
        "A pack/count conflict only if the catalog number cannot mean what is shown.",
        "Pairs:",
    ]
    for pair in pairs:
        lines.append(
            f"- id={pair.pair_id} type={CONFLICT_TYPE_LABELS.get(pair.kind, pair.kind)} "
            f"field={pair.field} catalog={pair.catalog_value!r} other={pair.observed!r}"
        )
    return "\n".join(lines)


def _score(raw: Any) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return max(0, min(100, int(round(float(raw)))))


def parse_judge_payload(
    parsed: dict[str, Any],
    pairs: list[JudgePair],
    sku_id: str,
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
                confidence=_score(item.get("certainty")),
                similarity=_score(item.get("similarity")),
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
) -> list[Finding]:
    if not pairs:
        return []
    parsed = client.call_tool(
        judge_prompt(pairs),
        model=model,
        tool=INBOUND_QC_JUDGE_TOOL,
        max_tokens=_JUDGE_MAX_TOKENS,
    )
    if not isinstance(parsed, dict):
        raise ValueError("inbound QC judge returned a non-object")
    return parse_judge_payload(parsed, pairs, sku_id)
