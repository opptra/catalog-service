"""Regenerate a single attribute value from user improvement notes.

v1 stored prompt is the unique brief (exact image-maker text or text strategy). Later
versions store only this regen's user note. Each image regen sends: v1 brief + this note,
with current output and product photos attached at render time — never a stack of older
notes or a re-dump of PRODUCT DATA.
"""

import json
from dataclasses import dataclass

from core.clients.openrouter import OpenRouterClient, ReferenceImage
from core.config import settings
from entities.catalog.attribute_enums import AttributeName
from pipelines.generation import prompts, tools
from pipelines.generation.context import GenerationContext
from pipelines.generation.images import (
    _GEMINI_ASPECT_RATIOS,
    _GPT_ASPECT_RATIOS,
    ImageGeneration,
    _normalize_aspect_ratio,
    _references,
    resolve_image_model,
)


@dataclass(frozen=True, slots=True)
class TextRegeneration:
    value: str
    prompt: str


def regenerate_image(
    client: OpenRouterClient,
    ctx: GenerationContext,
    *,
    origin_brief: str,
    improvement: str,
    aspect_ratio: str,
    current_image_url: str,
    session_id: str | None = None,
) -> ImageGeneration:
    """Re-render from v1 brief + current image + this user note + product refs."""
    base = origin_brief.strip()
    addendum = prompts.image_regeneration_addendum(improvement=improvement)
    image_prompt = f"{base}\n\n{addendum}"
    references = [
        ReferenceImage(
            url=current_image_url,
            label=(
                "CURRENT OUTPUT — the image the user wants improved. Preserve product identity "
                "and overall composition unless the requested change explicitly requires it."
            ),
        ),
        *_references(ctx),
    ]
    model = settings.openrouter_image_model
    render_fn = resolve_image_model(model)

    if render_fn.__name__ == "render_gpt":
        labeled_prompt = (
            f"{image_prompt}\n\n"
            "Reference images: the first attached image is the CURRENT OUTPUT to improve; "
            "the remaining images are the real product (colour/shape/material truth)."
        )
        image = client.generate_gpt_image(
            labeled_prompt,
            model=model,
            references=references,
            aspect_ratio=_normalize_aspect_ratio(aspect_ratio, _GPT_ASPECT_RATIOS),
            session_id=session_id,
        )
        return ImageGeneration(
            content=image.content,
            content_type=image.content_type,
            prompt=improvement.strip(),
        )

    image = client.generate_gemini_image(
        image_prompt,
        model=model,
        references=references,
        aspect_ratio=_normalize_aspect_ratio(aspect_ratio, _GEMINI_ASPECT_RATIOS),
        session_id=session_id,
    )
    return ImageGeneration(
        content=image.content,
        content_type=image.content_type,
        prompt=improvement.strip(),
    )


def regenerate_text(
    client: OpenRouterClient,
    ctx: GenerationContext,
    *,
    name: AttributeName,
    origin_brief: str,
    current_value: str,
    improvement: str,
    limit: tools.TextLimit | None = None,
    session_id: str | None = None,
) -> TextRegeneration:
    """Regenerate from v1 brief + current copy + this user note. Persist the note only."""
    parts = prompts.text_regeneration_parts(
        ctx,
        name,
        origin_brief=origin_brief,
        current_value=current_value,
        improvement=improvement,
    )
    limits = {name: limit} if limit is not None else None
    tool = tools.text_attributes_tool([name], limits=limits)
    parsed = client.call_tool(
        parts.suffix,
        model=settings.openrouter_text_model,
        tool=tool,
        cache_prefix=parts.prefix,
        session_id=session_id,
    )
    raw = parsed.get(name.value)
    if raw is None:
        raise ValueError(f"Text regeneration missing attribute: {name.value}")
    fitted = tools.apply_text_limits(name, raw, limit)
    if name in tools.LIST_TEXT_ATTRIBUTES:
        value = json.dumps(fitted if isinstance(fitted, list) else [], ensure_ascii=False)
    else:
        value = str(fitted)
    return TextRegeneration(value=value, prompt=improvement.strip())
