"""Stage 1: plan a coherent, non-duplicated image set for one attribute type per call.

IMAGE (PDP gallery) and A_PLUS are planned in separate tool calls. Each call sees the product
image and Category Intelligence role palette and returns a ready prompt per slot. No fallback:
a plan that fails or doesn't cover every requested slot is rejected outright.
"""

import logging
from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from core.exceptions import GalleryPlanError
from entities.catalog.attribute_enums import AttributeName
from pipelines.generation import prompts, tools
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
            model=settings.openrouter_prompt_model,
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
