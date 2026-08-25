"""Stage 1: plan a coherent, non-duplicated image set for one attribute type per call.

IMAGE (PDP gallery) and A_PLUS are planned separately. Per track: gather claim keys →
fact board values → deterministic claim ownership (max_callouts upstream) → assemble
a per-slot image brief (CI content/pattern, owned facts, JSON DNA fonts/colors).
That brief is sent straight to the image model — no Scene rewrite step.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from core.exceptions import GalleryPlanError
from entities.catalog.attribute_enums import AttributeName
from pipelines.generation import common_image, tools
from pipelines.generation.context import GenerationContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SlotPlan:
    """One slot, ready for the image model.

    ``prompt`` is the assembled slot brief sent to the image model (CI recipe,
    owned facts, and JSON DNA). ``role`` / ``kind`` are CI slot fields passed to
    the verifier as context only. No separate Scene rewrite.
    """

    name: AttributeName
    slot: int
    prompt: str
    concept: str | None = None
    role: str | None = None
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class FactValue:
    """One verified PRODUCT DATA snippet bound to a CI claim."""

    value: str
    source_field: str


@dataclass(frozen=True, slots=True)
class AssignedFact:
    claim: str
    value: str
    source_field: str


@dataclass(frozen=True, slots=True)
class AllocatedSlot:
    slot_def: dict[str, Any]
    concept: str
    owned_claims: list[str]
    assigned_facts: list[AssignedFact]


# Fact board: CI claim → verified values (same claim may have many source fields).
FactBoard = dict[str, list[FactValue]]


def _plan_model() -> str:
    """Model for structured planning/extraction (fact board, writers)."""
    return settings.openrouter_text_model


def _track_key(name: AttributeName) -> str:
    if name == AttributeName.IMAGE:
        return "gallery"
    if name == AttributeName.A_PLUS:
        return "aplus"
    return str(name.value).lower()


def _slot_order_key(slot: dict[str, Any]) -> int:
    order = slot.get("order")
    return order if isinstance(order, int) else 10**9


def _dup_key(slot: dict[str, Any]) -> str:
    owns = slot.get("owns")
    if isinstance(owns, str) and owns.strip():
        return owns.strip()
    role = slot.get("role")
    if isinstance(role, str) and role.strip():
        return role.strip()
    order = slot.get("order")
    if isinstance(order, int):
        return f"order:{order}"
    return json.dumps(slot, ensure_ascii=False, sort_keys=True)[:200]


def _candidate_ci_slots(ctx: GenerationContext, name: AttributeName) -> list[dict[str, Any]]:
    raw_plan = ctx.category_intelligence.get("image_plan")
    if not isinstance(raw_plan, dict):
        raise GalleryPlanError("category_intelligence.image_plan missing or not an object")

    track_key = _track_key(name)
    track = raw_plan.get(track_key)
    if not isinstance(track, dict):
        raise GalleryPlanError(f"category_intelligence.image_plan.{track_key} missing")

    slots_raw = track.get("slots")
    if not isinstance(slots_raw, list):
        raise GalleryPlanError(f"category_intelligence.image_plan.{track_key}.slots missing")

    slots = [s for s in slots_raw if isinstance(s, dict)]
    core = sorted(
        (s for s in slots if str(s.get("priority", "")).lower() == "core"),
        key=_slot_order_key,
    )
    extended = sorted(
        (s for s in slots if str(s.get("priority", "")).lower() != "core"),
        key=_slot_order_key,
    )
    return core + extended


def _feature_priority(slot: dict[str, Any]) -> list[str]:
    raw = slot.get("feature_priority")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _max_callouts(slot: dict[str, Any]) -> int:
    raw = slot.get("max_callouts")
    return raw if isinstance(raw, int) and raw >= 0 else 0


def _slot_text_field(slot: dict[str, Any], key: str) -> str:
    raw = slot.get(key)
    return raw.strip() if isinstance(raw, str) and raw.strip() else ""


def _slot_concept(slot: dict[str, Any]) -> str:
    role = _slot_text_field(slot, "role")
    if role:
        return role
    content = _slot_text_field(slot, "content")
    if content:
        return content.split(".", 1)[0].strip() or content[:80]
    return "catalog shot"


def _normalize_value(value: str) -> str:
    return " ".join(value.casefold().split())


def _fact_board_prompt(product: dict[str, Any], claims: list[str]) -> str:
    facts = {key: value for key, value in product.items() if key != "source_assets"}
    return (
        "You bind category feature-priority claims to this SKU's PRODUCT DATA.\n"
        "\n"
        "RULES:\n"
        "- PRODUCT DATA is the only source of facts.\n"
        "- For each CLAIM, return zero or more items that directly support it.\n"
        "- Prefer a short structured field over a marketing paragraph. Shorten at source "
        '(e.g. water temperature → "Machine Wash Cold", not the whole wash-care sentence).\n'
        '- If the cell is already short ("210", "Microfiber"), leave it. Do not expand '
        '"210" into "210 TC".\n'
        "- If a claim names more than one independent spec that this SKU actually has "
        "(e.g. cover length and cover width), return ONE item per spec with the same claim "
        "string, different values, and the matching source_field for each.\n"
        "- If only one of those specs exists, return only that one. If none can be "
        "determined, return nothing for that claim.\n"
        "- If the claim cannot be determined — no field, several conflicting fields, or "
        "the only hit is not shopper-facing — return no items for it. Never invent.\n"
        "- Every value must be a verbatim substring of its source_field value.\n"
        "- source_field must be an exact PRODUCT DATA key.\n"
        "- Copy each CLAIM string exactly (same spelling and punctuation).\n"
        "- Do not return empty-value rows; omit the claim instead.\n"
        "\n"
        "PRODUCT DATA (opaque strings/columns):\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}\n"
        "\n"
        f"CLAIMS (feature_priority strings): {json.dumps(claims, ensure_ascii=False)}\n"
    )


def _verify_fact_item(
    *,
    claim: str,
    value: str,
    source_field: str,
) -> str | None:
    """Return a drop reason, or None when the item is kept.

    Only empty claim/value/source_field rows are dropped — no other filtering.
    """
    if not claim.strip() or not value.strip() or not source_field.strip():
        return "empty"
    return None


def _build_fact_board(
    client: OpenRouterClient,
    ctx: GenerationContext,
    *,
    claims: list[str],
    session_id: str | None,
) -> FactBoard:
    """Return {claim: [FactValue, ...]} — omitted claims are absent or empty."""
    if not claims:
        return {}

    llm_prompt = _fact_board_prompt(ctx.product, claims)
    parsed = client.call_tool(
        llm_prompt,
        model=_plan_model(),
        tool=tools.gallery_fact_board_tool(),
        max_tokens=4096,
        session_id=session_id,
    )
    raw_facts = parsed.get("facts") if isinstance(parsed, dict) else None
    if not isinstance(raw_facts, list):
        raise GalleryPlanError("fact board missing facts array")

    allowed = set(claims)
    out: FactBoard = {claim: [] for claim in claims}
    seen_per_claim: dict[str, set[str]] = {claim: set() for claim in claims}

    for entry in raw_facts:
        if not isinstance(entry, dict):
            continue
        claim = entry.get("claim")
        value = entry.get("value")
        source_field = entry.get("source_field")
        if not isinstance(claim, str) or claim not in allowed:
            continue
        if not isinstance(value, str) or not isinstance(source_field, str):
            continue
        cleaned = value.strip()
        field = source_field.strip()
        reason = _verify_fact_item(
            claim=claim,
            value=cleaned,
            source_field=field,
        )
        if reason is not None:
            logger.info(
                "fact board drop claim=%r value=%r field=%r reason=%s",
                claim,
                cleaned,
                field,
                reason,
            )
            continue
        norm = _normalize_value(cleaned)
        if norm in seen_per_claim[claim]:
            continue
        seen_per_claim[claim].add(norm)
        out[claim].append(FactValue(value=cleaned, source_field=field))

    for claim, values in out.items():
        if not values:
            logger.info("fact board omit claim=%r reason=unmatched_or_filtered", claim)

    return out


def _slot_has_any_fact(*, slot: dict[str, Any], fact_board: FactBoard) -> bool:
    priorities = _feature_priority(slot)
    if not priorities:
        return True
    return any(bool(fact_board.get(claim)) for claim in priorities)


def _select_slots(
    candidate_slots: list[dict[str, Any]],
    *,
    quantity: int,
    fact_board: FactBoard,
) -> list[dict[str, Any]]:
    """Select exactly ``quantity`` slots (dedupe by owns; prefer fact-supported overlays)."""
    selected: list[dict[str, Any]] = []
    used: set[str] = set()

    for slot in candidate_slots:
        if len(selected) >= quantity:
            break
        key = _dup_key(slot)
        if key in used:
            continue
        if not _slot_has_any_fact(slot=slot, fact_board=fact_board):
            continue
        used.add(key)
        selected.append(slot)

    if len(selected) < quantity:
        for slot in candidate_slots:
            if len(selected) >= quantity:
                break
            key = _dup_key(slot)
            if key in used:
                continue
            used.add(key)
            selected.append(slot)

    if len(selected) != quantity:
        raise GalleryPlanError(
            f"slot selection produced {len(selected)}/{quantity} slots for {candidate_slots=}"
        )
    return selected


def _facts_for_claims(
    owned_claims: list[str],
    fact_board: FactBoard,
) -> list[AssignedFact]:
    out: list[AssignedFact] = []
    seen_values: set[str] = set()
    for claim in owned_claims:
        for item in fact_board.get(claim, []):
            norm = _normalize_value(item.value)
            if norm in seen_values:
                continue
            seen_values.add(norm)
            out.append(
                AssignedFact(
                    claim=claim,
                    value=item.value,
                    source_field=item.source_field,
                )
            )
    return out


def _own_claims_for_slots(
    *,
    chosen_slots: list[dict[str, Any]],
    fact_board: FactBoard,
) -> list[list[str]]:
    """Deterministic ownership: CI feature_priority ∩ fact board, capped by max_callouts.

    Earlier slots win when the same claim appears in more than one slot's priority list.
    """
    owned_by_slot: list[list[str]] = []
    claim_owner: dict[str, int] = {}
    for slot_index, slot_def in enumerate(chosen_slots):
        priorities = _feature_priority(slot_def)
        cap = _max_callouts(slot_def)
        kept: list[str] = []
        used_values: set[str] = set()
        for claim in priorities:
            if cap >= 0 and len(kept) >= cap:
                break
            values = fact_board.get(claim) or []
            if not values:
                continue
            if claim in claim_owner:
                logger.info(
                    "ownership skip claim=%r slot=%s reason=owned_by_slot_%s",
                    claim,
                    slot_index + 1,
                    claim_owner[claim] + 1,
                )
                continue
            norms = {_normalize_value(item.value) for item in values}
            if norms & used_values:
                logger.info(
                    "ownership skip claim=%r slot=%s reason=duplicate_value_in_slot",
                    claim,
                    slot_index + 1,
                )
                continue
            used_values |= norms
            claim_owner[claim] = slot_index
            kept.append(claim)
        owned_by_slot.append(kept)
    return owned_by_slot


def _allocate_slots(
    *,
    chosen_slots: list[dict[str, Any]],
    fact_board: FactBoard,
) -> list[AllocatedSlot]:
    """Map chosen CI slots to owned claims and verified facts (no LLM)."""
    owned_by_slot = _own_claims_for_slots(
        chosen_slots=chosen_slots,
        fact_board=fact_board,
    )
    allocated: list[AllocatedSlot] = []
    for slot_def, owned in zip(chosen_slots, owned_by_slot, strict=True):
        allocated.append(
            AllocatedSlot(
                slot_def=slot_def,
                concept=_slot_concept(slot_def),
                owned_claims=owned,
                assigned_facts=_facts_for_claims(owned, fact_board),
            )
        )
    return allocated


def _facts_block(assigned_facts: list[AssignedFact]) -> str:
    """JSON list of assigned facts for the image-model brief."""
    if not assigned_facts:
        return "[]"
    payload = [
        {
            "claim": fact.claim,
            "source_field": fact.source_field,
            "value": fact.value,
        }
        for fact in assigned_facts
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _slot_prompt(
    *,
    slot: dict[str, Any],
    assigned_facts: list[AssignedFact],
    brand_look: str,
) -> str:
    """Assemble the image-model brief for one slot (no Scene rewrite)."""
    role = _slot_text_field(slot, "role")
    kind = _slot_text_field(slot, "kind")
    content = _slot_text_field(slot, "content")
    pattern = _slot_text_field(slot, "pattern")
    slot_line = " — ".join(part for part in (role, kind) if part) or "catalog shot"

    lines = [
        "Create this image from the product reference photos attached to this call.",
        "",
        f"Slot: {slot_line}",
    ]
    if content:
        lines.append(f"Content: {content}")
    if pattern:
        lines.append(f"Pattern: {pattern}")
    dna_block = common_image.format_block(brand_look)
    if dna_block:
        lines.append(dna_block)
    lines.append("")

    if assigned_facts:
        lines.append(
            "This shot has required on-image facts as JSON below. Render every fact "
            "visibly and legibly in the finished image. Preserve each value exactly: "
            "do not omit, paraphrase, restyle, or invent facts."
        )
        lines.append(
            'Paint ONLY each object\'s "value" string on the image. Do not paint '
            '"claim", "source_field", JSON keys, braces, quotes, or commas.'
        )
        lines.append(_facts_block(assigned_facts))
        lines.append(
            "Integrate the text as a restrained catalog-style overlay in a readable "
            "area without materially changing the requested photography."
        )
    else:
        lines.append(
            "This shot has no on-image facts. Paint no product specs, slogans, size "
            "charts, icon strips, or promotional copy."
        )

    lines.extend(
        [
            "",
            "Render the shot described by Content and Pattern above.",
            "Keep the product appearance from the reference photos as the visual priority.",
            "Do not draw a logo. Do not invent claims. Do not mention canvas ratio or font names.",
        ]
    )
    return "\n".join(lines)


def _plan_slot_prompt(
    ctx: GenerationContext,
    *,
    slot: dict[str, Any],
    assigned_facts: list[AssignedFact],
) -> str:
    """Assemble the image brief for one slot — no Scene-writer LLM call."""
    return _slot_prompt(
        slot=slot,
        assigned_facts=assigned_facts,
        brand_look=ctx.compressed_brand_dna or "",
    )


def plan_selected_slots(
    client: OpenRouterClient,
    ctx: GenerationContext,
    name: AttributeName,
    quantity: int,
    *,
    session_id: str | None = None,
) -> dict[tuple[AttributeName, int], SlotPlan]:
    """Plan exactly ``quantity`` slots for one image attribute track."""
    if quantity < 1:
        raise GalleryPlanError(f"quantity must be >= 1 for {name.value}")

    candidate_slots = _candidate_ci_slots(ctx, name)
    if not candidate_slots:
        raise GalleryPlanError(f"no candidate CI slots for {name.value}")

    all_claims: list[str] = []
    for slot in candidate_slots:
        all_claims.extend(_feature_priority(slot))
    claims = sorted(set(all_claims))

    fact_board = _build_fact_board(
        client,
        ctx,
        claims=claims,
        session_id=session_id,
    )
    chosen_slots = _select_slots(candidate_slots, quantity=quantity, fact_board=fact_board)
    allocated = _allocate_slots(chosen_slots=chosen_slots, fact_board=fact_board)

    out: dict[tuple[AttributeName, int], SlotPlan] = {}
    for slot_position, item in enumerate(allocated, start=1):
        final_prompt = _plan_slot_prompt(
            ctx,
            slot=item.slot_def,
            assigned_facts=item.assigned_facts,
        )
        out[(name, slot_position)] = SlotPlan(
            name=name,
            slot=slot_position,
            prompt=final_prompt,
            concept=item.concept,
            role=_slot_text_field(item.slot_def, "role") or None,
            kind=_slot_text_field(item.slot_def, "kind") or None,
        )
    return out
