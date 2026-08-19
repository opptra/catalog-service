"""Stage 1: plan a coherent, non-duplicated image set for one attribute type per call.

IMAGE (PDP gallery) and A_PLUS are planned in separate tool calls. Each call sees the product
image and Category Intelligence role palette and returns a ready prompt per slot. No fallback:
a plan that fails or doesn't cover every requested slot is rejected outright.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from core.exceptions import GalleryPlanError
from entities.catalog.attribute_enums import AttributeName
from pipelines.generation import common_image, prompts, tools
from pipelines.generation.context import GenerationContext

logger = logging.getLogger(__name__)

# Token budget scales with gallery size — a bigger gallery genuinely needs more output tokens
# (one complete standalone prompt per slot plus the shared_style paragraph). Calibrated from
# live measurements against openai/gpt-5.4-mini across 3/6/10-image galleries.
_PLAN_TOKENS_BASE = 400
_PLAN_TOKENS_PER_SLOT = 210
_PLAN_TOKENS_SAFETY_MULTIPLIER = 1.5


def _plan_max_tokens(num_slots: int) -> int:
    """Token budget for a plan call requesting ``num_slots`` images, with a safety margin."""
    raw = _PLAN_TOKENS_BASE + _PLAN_TOKENS_PER_SLOT * num_slots
    return int(raw * _PLAN_TOKENS_SAFETY_MULTIPLIER)


@dataclass(frozen=True, slots=True)
class SlotPlan:
    name: AttributeName
    slot: int
    prompt: str
    concept: str | None = None


@dataclass(frozen=True, slots=True)
class AssignedFact:
    claim: str
    value: str


def _plan_model() -> str:
    """Model for structured planning/extraction (slot selection + per-slot prompts)."""
    return settings.openrouter_text_model


def _track_key(name: AttributeName) -> str:
    if name == AttributeName.IMAGE:
        return "gallery"
    if name == AttributeName.A_PLUS:
        return "aplus"
    # Defensive: AttributeName should be locked by the caller.
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


def _fact_board_prompt(product: dict[str, Any], claims: list[str]) -> str:
    return (
        "You extract verbatim product facts for on-image labels.\n"
        "\n"
        "RULES:\n"
        "- PRODUCT DATA is the only source of facts.\n"
        "- For each CLAIM, find an exact value that directly supports that claim.\n"
        "- Prefer short structured spec fields over long marketing paragraphs.\n"
        "- If a claim is only supported by taxonomy/category labels, return empty string.\n"
        "- The output value must be copied verbatim from PRODUCT DATA.\n"
        "- If PRODUCT DATA does not contain a supporting value, return an empty string.\n"
        "- Never invent, infer, or rephrase into a new value.\n"
        "\n"
        "PRODUCT DATA (opaque strings/columns):\n"
        f"{json.dumps(product, ensure_ascii=False, indent=2)}\n"
        "\n"
        f"CLAIMS (feature_priority strings): {json.dumps(claims, ensure_ascii=False)}\n"
    )


def _build_fact_board(
    client: OpenRouterClient,
    ctx: GenerationContext,
    *,
    claims: list[str],
    session_id: str | None,
) -> dict[str, str]:
    """Return {claim: exact_value | ''} extracted from PRODUCT DATA."""
    if not claims:
        return {}

    parsed = client.call_tool(
        _fact_board_prompt(ctx.product, claims),
        model=_plan_model(),
        tool=tools.gallery_fact_board_tool(),
        max_tokens=4096,
        session_id=session_id,
    )
    raw_facts = parsed.get("facts") if isinstance(parsed, dict) else None
    if not isinstance(raw_facts, list):
        raise GalleryPlanError("fact board missing facts array")

    out: dict[str, str] = {}
    for entry in raw_facts:
        if not isinstance(entry, dict):
            continue
        claim = entry.get("claim")
        value = entry.get("value")
        if not isinstance(claim, str) or not claim.strip():
            continue
        if not isinstance(value, str):
            continue
        out[claim] = value.strip()

    # Ensure stable keys: any missing claim becomes '' so selection can treat it as unsupported.
    for claim in claims:
        out.setdefault(claim, "")
    return out


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


def _assigned_facts_for_slot(
    *,
    slot: dict[str, Any],
    fact_board: dict[str, str],
) -> list[AssignedFact]:
    priorities = _feature_priority(slot)
    if not priorities:
        return []
    cap = _max_callouts(slot)
    if cap == 0:
        return []
    out: list[AssignedFact] = []
    for claim in priorities:
        value = fact_board.get(claim, "")
        if not isinstance(value, str) or not value.strip():
            continue
        out.append(AssignedFact(claim=claim, value=value.strip()))
        if len(out) >= cap:
            break
    return out


def _slot_has_any_fact(*, slot: dict[str, Any], fact_board: dict[str, str]) -> bool:
    priorities = _feature_priority(slot)
    if not priorities:
        return True
    return any(bool(fact_board.get(claim, "").strip()) for claim in priorities)


def _select_slots(
    candidate_slots: list[dict[str, Any]],
    *,
    quantity: int,
    fact_board: dict[str, str],
) -> list[tuple[dict[str, Any], list[AssignedFact]]]:
    """Select exactly `quantity` slots.

    Rules:
    - Deduplicate by `owns` (fallback to role) within the track.
    - First pass: eligible overlays require at least one supported fact.
    - Second pass: if still short, fill remaining non-duplicate slots even when facts are empty
      (prompt will omit on-image text when assigned_facts is empty).
    """
    selected: list[tuple[dict[str, Any], list[AssignedFact]]] = []
    used: set[str] = set()

    # Pass 1: eligible slots only.
    for slot in candidate_slots:
        if len(selected) >= quantity:
            break
        key = _dup_key(slot)
        if key in used:
            continue
        if not _slot_has_any_fact(slot=slot, fact_board=fact_board):
            continue
        used.add(key)
        selected.append((slot, _assigned_facts_for_slot(slot=slot, fact_board=fact_board)))

    # Pass 2: fill to quantity with remaining slots.
    if len(selected) < quantity:
        for slot in candidate_slots:
            if len(selected) >= quantity:
                break
            key = _dup_key(slot)
            if key in used:
                continue
            used.add(key)
            selected.append((slot, _assigned_facts_for_slot(slot=slot, fact_board=fact_board)))

    if len(selected) != quantity:
        raise GalleryPlanError(
            f"slot selection produced {len(selected)}/{quantity} slots for {candidate_slots=}"
        )
    return selected


def _slot_prompt(
    *,
    name: AttributeName,
    output_slot: int,
    slot: dict[str, Any],
    assigned_facts: list[AssignedFact],
    sibling_concepts: list[str],
    shared_style: str,
    common_block: str,
) -> str:
    role = slot.get("role") if isinstance(slot.get("role"), str) else ""
    kind = slot.get("kind") if isinstance(slot.get("kind"), str) else ""
    pattern = slot.get("pattern") if isinstance(slot.get("pattern"), str) else ""
    content = slot.get("content") if isinstance(slot.get("content"), str) else ""
    max_callouts = _max_callouts(slot)

    if assigned_facts:
        facts_block = "\n".join(f"- claim: {fact.claim} | value: {fact.value}" for fact in assigned_facts)
    else:
        facts_block = "(none — print no on-image text)"
    sibling_block = "\n".join(f"- {concept}" for concept in sibling_concepts) or "(none)"
    return (
        "You are creating a standalone prompt for generating ONE e-commerce product image.\n"
        "\n"
        f"ATTRIBUTE TYPE: {name.value}\n"
        f"OUTPUT SLOT: {output_slot} (1..quantity)\n"
        "\n"
        "SLOT RECIPE (category guidance; not a source of facts):\n"
        f"- role: {role}\n"
        f"- kind: {kind}\n"
        f"- pattern: {pattern}\n"
        f"- content: {content}\n"
        "\n"
        f"ON-IMAGE TEXT BUDGET: max_callouts={max_callouts} (upper bound only).\n"
        "SOURCE FACTS (meaning + product value; not on-image copy):\n"
        f"{facts_block}\n"
        "\n"
        "ALREADY-CHOSEN SLOT CONCEPTS FOR THIS TRACK (avoid overlap):\n"
        f"{sibling_block}\n"
        "\n"
        "SHARED VISUAL SYSTEM:\n"
        f"{shared_style}\n"
        "\n"
        f"{common_block}\n"
        "\n"
        "HARD RULES:\n"
        f"- Use at most {max_callouts} on-image labels.\n"
        "- If there are no source facts, print NO on-image text at all.\n"
        "- Distill source facts into short shopper-facing labels; do not copy long paragraphs.\n"
        "- Claim keys are planner metadata. Never print claim keys on artwork.\n"
        "- Never invent, infer, or add numbers/claims not supported by source facts.\n"
        "- Keep labels phone-readable with generous whitespace; avoid dense text walls.\n"
        "- Never print font family names on artwork.\n"
        f"{prompts.image_on_canvas_copy_rules()}\n"
        "\n"
        "Composition guidance:\n"
        "- Use the real product reference photos attached to the planning call.\n"
        "- The on-image text should match the slot recipe job visually "
        "(e.g., care module shows laundry-icons layout),\n"
        "  but without inventing extra facts.\n"
    )


def _plan_slot_prompt(
    client: OpenRouterClient,
    ctx: GenerationContext,
    *,
    name: AttributeName,
    slot_position: int,
    slot: dict[str, Any],
    assigned_facts: list[AssignedFact],
    sibling_concepts: list[str],
    shared_style: str,
    common_block: str,
    session_id: str | None,
) -> str:
    parsed = client.call_tool(
        _slot_prompt(
            name=name,
            output_slot=slot_position,
            slot=slot,
            assigned_facts=assigned_facts,
            sibling_concepts=sibling_concepts,
            shared_style=shared_style,
            common_block=common_block,
        ),
        model=_plan_model(),
        tool=tools.single_slot_prompt_tool(),
        image_urls=ctx.product_image_urls or None,
        max_tokens=900,
        session_id=session_id,
    )
    prompt = parsed.get("prompt") if isinstance(parsed, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        raise GalleryPlanError("slot prompt missing prompt string")
    return prompt.strip()


def _shared_style_prompt(
    *,
    name: AttributeName,
    chosen_slots: list[dict[str, Any]],
    common_block: str,
) -> str:
    slot_summary = "\n".join(
        f"- role={slot.get('role', '')} | kind={slot.get('kind', '')} | pattern={slot.get('pattern', '')}"
        for slot in chosen_slots
    )
    return (
        "Write one short shared visual-system paragraph for this image track.\n"
        f"ATTRIBUTE TYPE: {name.value}\n"
        "It must keep all slots cohesive while preserving slot-level distinction.\n"
        "Focus on: composition language, palette usage, text treatment, icon style, and lighting.\n"
        "Do not mention aspect ratio, font family names, CI keys, or internal attribute labels.\n"
        "Keep it concise and directly usable inside image prompts.\n\n"
        "CHOSEN SLOT ROLES:\n"
        f"{slot_summary}\n\n"
        f"{common_block}\n"
    )


def _plan_shared_style(
    client: OpenRouterClient,
    *,
    name: AttributeName,
    chosen_slots: list[dict[str, Any]],
    common_block: str,
    session_id: str | None,
) -> str:
    parsed = client.call_tool(
        _shared_style_prompt(name=name, chosen_slots=chosen_slots, common_block=common_block),
        model=_plan_model(),
        tool=tools.shared_style_tool(),
        max_tokens=220,
        session_id=session_id,
    )
    style = parsed.get("shared_style") if isinstance(parsed, dict) else None
    if not isinstance(style, str) or not style.strip():
        raise GalleryPlanError("shared style missing shared_style string")
    return style.strip()


def plan_selected_slots(
    client: OpenRouterClient,
    ctx: GenerationContext,
    name: AttributeName,
    quantity: int,
    *,
    session_id: str | None = None,
) -> dict[tuple[AttributeName, int], SlotPlan]:
    """Plan exactly `quantity` slots by:

    1) extracting a verbatim fact board from PRODUCT DATA for this track's `feature_priority`;
    2) selecting core/extended slots eligible for this SKU (no duplicate `owns` in-track);
    3) generating one standalone prompt per selected slot.

    This replaces the previous bulk multi-slot planning call so we can stop repeated facts and
    hardcoded competitor information from landing on the same SKU's images.
    """
    if quantity < 1:
        raise GalleryPlanError(f"quantity must be >= 1 for {name.value}")

    candidate_slots = _candidate_ci_slots(ctx, name)
    if not candidate_slots:
        raise GalleryPlanError(f"no candidate CI slots for {name.value}")

    # Build the universe of claims to support for this track.
    all_claims: list[str] = []
    for slot in candidate_slots:
        all_claims.extend(_feature_priority(slot))
    claims = sorted(set(all_claims))

    fact_board = _build_fact_board(client, ctx, claims=claims, session_id=session_id)
    chosen = _select_slots(candidate_slots, quantity=quantity, fact_board=fact_board)
    chosen_slots = [slot for slot, _ in chosen]
    common_block = (
        common_image.format_block(ctx.common_image_context)
        if ctx.common_image_context
        else (
            "=== COMMON IMAGE CONTEXT ===\n"
            "(missing — keep one cohesive visual system with sparse phone-readable labels and "
            "product-first compositions)"
        )
    )
    shared_style = _plan_shared_style(
        client,
        name=name,
        chosen_slots=chosen_slots,
        common_block=common_block,
        session_id=session_id,
    )
    sibling_concepts = [
        str(slot.get("role", "")).strip() for slot in chosen_slots if str(slot.get("role", "")).strip()
    ]

    out: dict[tuple[AttributeName, int], SlotPlan] = {}
    for slot_position, (slot_def, assigned_facts) in enumerate(chosen, start=1):
        prompt = _plan_slot_prompt(
            client,
            ctx,
            name=name,
            slot_position=slot_position,
            slot=slot_def,
            assigned_facts=assigned_facts,
            sibling_concepts=sibling_concepts,
            shared_style=shared_style,
            common_block=common_block,
            session_id=session_id,
        )
        out[(name, slot_position)] = SlotPlan(
            name=name,
            slot=slot_position,
            prompt=prompt,
            concept=slot_def.get("role") if isinstance(slot_def.get("role"), str) else None,
        )
    return out


def plan(
    client: OpenRouterClient,
    ctx: GenerationContext,
    name: AttributeName,
    quantity: int,
    *,
    session_id: str | None = None,
) -> dict[tuple[AttributeName, int], SlotPlan]:
    """Plan exactly ``quantity`` slots for one image attribute. Raises ``GalleryPlanError`` if
    the call fails or the plan doesn't cover slots 1..quantity — no fallback.
    """
    if quantity < 1:
        raise GalleryPlanError(f"quantity must be >= 1 for {name.value}")
    wanted = [(name, slot) for slot in range(1, quantity + 1)]
    try:
        parsed = client.call_tool(
            prompts.gallery_plan_prompt(ctx, name, quantity),
            model=settings.openrouter_text_model,
            tool=tools.gallery_plan_tool(name, quantity),
            image_urls=ctx.product_image_urls or None,
            max_tokens=_plan_max_tokens(quantity),
            session_id=session_id,
        )
        planned = _index_plan(parsed, name=name, quantity=quantity)
    except GalleryPlanError:
        raise
    except Exception as exc:
        logger.error("Gallery plan call failed for %s: %s", name.value, exc)
        raise GalleryPlanError(f"Gallery plan call failed for {name.value}: {exc}") from exc

    missing = [key for key in wanted if key not in planned]
    if missing:
        logger.error(
            "Gallery plan missing %d/%d slot(s) for %s: %s",
            len(missing),
            quantity,
            name.value,
            missing,
        )
        raise GalleryPlanError(
            f"Gallery plan missing {len(missing)}/{quantity} slot(s) for {name.value}"
        )

    return {key: planned[key] for key in wanted}


def _index_plan(
    parsed: dict[str, Any],
    *,
    name: AttributeName,
    quantity: int,
) -> dict[tuple[AttributeName, int], SlotPlan]:
    """Index slots 1..quantity for a single attribute type from the tool payload.

    Prefer the model's ``slot`` when it is a unique int in 1..quantity; otherwise assign by
    order of appearance so a slight numbering slip does not orphan the plan. Entries for any
    other type are ignored (the tool schema already locks type).

    Stored prompt is the unique slot brief (+ shared style). Common image context and
    render-rule suffix are applied at render time, not persisted.
    """
    shared_style = parsed.get("shared_style") or ""
    raw_slots = parsed.get("slots")
    if not isinstance(raw_slots, list):
        raw_slots = []

    entries: list[dict[str, Any]] = []
    for entry in raw_slots:
        if not isinstance(entry, dict):
            continue
        try:
            entry_name = AttributeName(str(entry["type"]).strip().upper())
            prompt = entry["prompt"]
        except (KeyError, ValueError, TypeError):
            continue
        if entry_name != name:
            continue
        if not isinstance(prompt, str) or not prompt.strip():
            continue
        entries.append(entry)

    if len(entries) != quantity:
        raise GalleryPlanError(
            f"Gallery plan for {name.value} returned {len(entries)} slot(s); expected {quantity}"
        )

    # Use model slot numbers when they are a clean permutation of 1..quantity.
    by_slot: dict[int, dict[str, Any]] = {}
    slot_ok = True
    for entry in entries:
        slot = entry.get("slot")
        if not isinstance(slot, int) or slot < 1 or slot > quantity or slot in by_slot:
            slot_ok = False
            break
        by_slot[slot] = entry
    if not slot_ok or len(by_slot) != quantity:
        by_slot = dict(enumerate(entries, start=1))

    indexed: dict[tuple[AttributeName, int], SlotPlan] = {}
    for slot, entry in by_slot.items():
        full_prompt = entry["prompt"].strip()
        if shared_style:
            full_prompt = f"{full_prompt}\n\nShared visual system (keep consistent): {shared_style}"
        indexed[(name, slot)] = SlotPlan(
            name=name,
            slot=slot,
            prompt=full_prompt,
            concept=entry.get("concept"),
        )
    return indexed
