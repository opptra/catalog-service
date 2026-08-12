"""Stage 1: plan a coherent, non-duplicated image gallery in one coordinated reasoning call.

The planner sees the real product image and the Category Intelligence gallery guidance and returns
a ready prompt per (type, slot) for IMAGE (PDP gallery) and/or A_PLUS. Roles come from CI, not from
fixed hero/infographic/lifestyle templates. No fallback: a plan that fails or doesn't cover every
requested slot is rejected outright, so a bad plan never silently ships a low-quality image.
"""

import logging
from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from core.exceptions import GalleryPlanError
from entities.catalog.attribute_enums import AttributeName
from generation import prompts, tools
from generation.context import GenerationContext

logger = logging.getLogger(__name__)

# Token budget for the plan call scales with gallery size, not a flat constant — a bigger
# requested gallery genuinely needs more output tokens (one complete standalone prompt per
# slot plus the shared shared_style paragraph), so a fixed cap either wastes headroom on small
# galleries or risks truncating large ones. Calibrated from live measurements against
# openai/gpt-5.4-mini across 3/6/10-image galleries (~309/302/236 completion tokens per image,
# ~202 tokens/image marginal cost by linear fit, ~400 token fixed overhead for shared_style):
# base + per-slot cost, times a safety multiplier for normal run-to-run variance.
_PLAN_TOKENS_BASE = 400
_PLAN_TOKENS_PER_SLOT = 210
_PLAN_TOKENS_SAFETY_MULTIPLIER = 1.5

# Appended via prompts.ensure_image_render_suffix() — single source in prompts.py.


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
    requested: list[tuple[AttributeName, int]],
) -> dict[tuple[AttributeName, int], SlotPlan]:
    """Plan every (type, slot) as one coherent gallery. Raises ``GalleryPlanError`` if the call
    fails, or if the model's plan doesn't cover every requested (type, slot) — no fallback.
    """
    wanted = [(name, slot) for name, quantity in requested for slot in range(1, quantity + 1)]
    try:
        parsed = client.call_tool(
            prompts.gallery_plan_prompt(ctx, requested),
            model=settings.openrouter_prompt_model,
            tool=tools.GALLERY_PLAN_TOOL,
            image_urls=ctx.product_image_urls or None,
            max_tokens=_plan_max_tokens(len(wanted)),
        )
        planned = _index_plan(parsed)
    except Exception as exc:
        logger.error("Gallery plan call failed: %s", exc)
        raise GalleryPlanError(f"Gallery plan call failed: {exc}") from exc

    missing = [key for key in wanted if key not in planned]
    if missing:
        logger.error("Gallery plan missing %d/%d slot(s): %s", len(missing), len(wanted), missing)
        raise GalleryPlanError(f"Gallery plan missing {len(missing)}/{len(wanted)} slot(s)")

    return {key: planned[key] for key in wanted}


def _index_plan(parsed: dict[str, Any]) -> dict[tuple[AttributeName, int], SlotPlan]:
    """Index the model's slots by (type, within-type position) — never by its own "slot" number.

    The model sometimes numbers "slot" as a running count across the whole gallery (e.g. IMAGE=1..7
    then A_PLUS continuing at 8) instead of restarting at 1 per type, which silently orphaned every
    slot after the first. Assigning the slot index ourselves from each type's order of appearance
    is correct regardless of what convention the model used.
    """
    shared_style = parsed.get("shared_style") or ""
    by_type: dict[AttributeName, list[dict[str, Any]]] = {}
    for entry in parsed.get("slots", []):
        try:
            name = AttributeName(str(entry["type"]).strip().upper())
            prompt = entry["prompt"]
        except (KeyError, ValueError, TypeError):
            continue
        if not isinstance(prompt, str) or not prompt.strip():
            continue
        by_type.setdefault(name, []).append(entry)

    indexed: dict[tuple[AttributeName, int], SlotPlan] = {}
    for name, entries in by_type.items():
        for slot, entry in enumerate(entries, start=1):
            # Fold the shared visual system into each slot prompt so the set stays linked.
            full_prompt = entry["prompt"].strip()
            if shared_style:
                full_prompt = (
                    f"{full_prompt}\n\nShared visual system (keep consistent): {shared_style}"
                )
            full_prompt = prompts.ensure_image_render_suffix(full_prompt)
            indexed[(name, slot)] = SlotPlan(
                name=name,
                slot=slot,
                prompt=full_prompt,
                concept=entry.get("concept"),
            )
    return indexed
