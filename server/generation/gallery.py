"""Two-step image gallery planning.

Step 1 maps Category Intelligence to a minimal gallery sequence (role / visual / objective).
Step 2 expands that sequence into complete image-generation prompts. No fallback: missing slots
fail the plan.
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

# Step 1 output is tiny (role + visual + objective per slot).
_BRIEF_TOKENS_BASE = 150
_BRIEF_TOKENS_PER_SLOT = 40
_BRIEF_TOKENS_SAFETY_MULTIPLIER = 1.5

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

# Appended to every slot prompt so the image model never invents a logo or reserved logo space;
# logos are composited later in a deterministic code step.
_NO_LOGO_PROMPT_SUFFIX = (
    "Brand logo: do not draw, render, watermark, or place any brand logo or brand name on the "
    "image. Do not leave empty reserved space, corners, banners, margins, or padding for a logo "
    "— the logo is added later by a deterministic code step."
)


def _brief_max_tokens(num_slots: int) -> int:
    """Token budget for a step-1 brief call requesting ``num_slots`` images."""
    raw = _BRIEF_TOKENS_BASE + _BRIEF_TOKENS_PER_SLOT * num_slots
    return int(raw * _BRIEF_TOKENS_SAFETY_MULTIPLIER)


def _plan_max_tokens(num_slots: int) -> int:
    """Token budget for a step-2 plan call requesting ``num_slots`` images, with a safety margin."""
    raw = _PLAN_TOKENS_BASE + _PLAN_TOKENS_PER_SLOT * num_slots
    return int(raw * _PLAN_TOKENS_SAFETY_MULTIPLIER)


@dataclass(frozen=True, slots=True)
class SlotBrief:
    name: AttributeName
    slot: int
    role: str
    visual: str
    objective: str


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
    """Plan every (type, slot) via step-1 sequence then step-2 prompts.

    Raises ``GalleryPlanError`` if either call fails, or if either step doesn't cover every
    requested (type, slot) — no fallback.
    """
    wanted = [(name, slot) for name, quantity in requested for slot in range(1, quantity + 1)]
    briefs = plan_slot_briefs(client, ctx, requested)
    brief_payload = [
        {
            "type": briefs[key].name.value,
            "slot": briefs[key].slot,
            "role": briefs[key].role,
            "visual": briefs[key].visual,
            "objective": briefs[key].objective,
        }
        for key in wanted
    ]

    try:
        parsed = client.call_tool(
            prompts.gallery_plan_prompt(ctx, requested, brief_payload),
            model=settings.openrouter_prompt_model,
            tool=tools.GALLERY_PLAN_TOOL,
            image_urls=ctx.product_image_urls or None,
            max_tokens=_plan_max_tokens(len(wanted)),
        )
        planned = _index_plan(parsed)
    except GalleryPlanError:
        raise
    except Exception as exc:
        logger.error("Gallery plan call failed: %s", exc)
        raise GalleryPlanError(f"Gallery plan call failed: {exc}") from exc

    missing = [key for key in wanted if key not in planned]
    if missing:
        logger.error("Gallery plan missing %d/%d slot(s): %s", len(missing), len(wanted), missing)
        raise GalleryPlanError(f"Gallery plan missing {len(missing)}/{len(wanted)} slot(s)")

    # Prefer the step-1 role when the step-2 plan omits a concept.
    result: dict[tuple[AttributeName, int], SlotPlan] = {}
    for key in wanted:
        slot_plan = planned[key]
        if not slot_plan.concept:
            slot_plan = SlotPlan(
                name=slot_plan.name,
                slot=slot_plan.slot,
                prompt=slot_plan.prompt,
                concept=briefs[key].role,
            )
        result[key] = slot_plan
    return result


def plan_slot_briefs(
    client: OpenRouterClient,
    ctx: GenerationContext,
    requested: list[tuple[AttributeName, int]],
) -> dict[tuple[AttributeName, int], SlotBrief]:
    """Step 1: one role/visual/objective per requested (type, slot)."""
    wanted = [(name, slot) for name, quantity in requested for slot in range(1, quantity + 1)]
    try:
        parsed = client.call_tool(
            prompts.slot_brief_prompt(ctx, requested),
            model=settings.openrouter_prompt_model,
            tool=tools.SLOT_BRIEF_TOOL,
            image_urls=ctx.product_image_urls or None,
            max_tokens=_brief_max_tokens(len(wanted)),
        )
        indexed = _index_briefs(parsed)
    except Exception as exc:
        logger.error("Gallery slot-brief call failed: %s", exc)
        raise GalleryPlanError(f"Gallery slot-brief call failed: {exc}") from exc

    missing = [key for key in wanted if key not in indexed]
    if missing:
        logger.error(
            "Gallery slot briefs missing %d/%d slot(s): %s", len(missing), len(wanted), missing
        )
        raise GalleryPlanError(f"Gallery slot briefs missing {len(missing)}/{len(wanted)} slot(s)")

    return {key: indexed[key] for key in wanted}


def _index_briefs(parsed: dict[str, Any]) -> dict[tuple[AttributeName, int], SlotBrief]:
    """Index step-1 sequence by (type, within-type position), not the model's slot number."""
    by_type: dict[AttributeName, list[dict[str, Any]]] = {}
    for entry in parsed.get("slots", []):
        try:
            name = AttributeName(str(entry["type"]).strip().upper())
            role = entry["role"]
            visual = entry["visual"]
            objective = entry["objective"]
        except (KeyError, ValueError, TypeError):
            continue
        if not isinstance(role, str) or not role.strip():
            continue
        if not isinstance(visual, str) or not visual.strip():
            continue
        if not isinstance(objective, str) or not objective.strip():
            continue
        by_type.setdefault(name, []).append(entry)

    indexed: dict[tuple[AttributeName, int], SlotBrief] = {}
    for name, entries in by_type.items():
        for slot, entry in enumerate(entries, start=1):
            indexed[(name, slot)] = SlotBrief(
                name=name,
                slot=slot,
                role=str(entry["role"]).strip(),
                visual=str(entry["visual"]).strip(),
                objective=str(entry["objective"]).strip(),
            )
    return indexed


def _index_plan(parsed: dict[str, Any]) -> dict[tuple[AttributeName, int], SlotPlan]:
    """Index the model's slots by (type, within-type position) — never by its own slot number."""
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
            full_prompt = f"{full_prompt}\n\n{_NO_LOGO_PROMPT_SUFFIX}"
            concept = entry.get("concept")
            indexed[(name, slot)] = SlotPlan(
                name=name,
                slot=slot,
                prompt=full_prompt,
                concept=concept if isinstance(concept, str) else None,
            )
    return indexed
