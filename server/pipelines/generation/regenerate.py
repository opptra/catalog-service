"""Regenerate a single attribute value from user improvement notes.

Flow: load previous prompt + current value → revise prompt → re-render (image or text)
→ persist a new version under the same value ``external_id``.
"""

import json
from dataclasses import dataclass

from core.clients.openrouter import OpenRouterClient, ReferenceImage
from core.config import settings
from entities.catalog.attribute_enums import AttributeDataType, AttributeName
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
class RevisedPrompt:
    prompt: str


@dataclass(frozen=True, slots=True)
class TextRegeneration:
    value: str
    prompt: str


def revise_prompt(
    client: OpenRouterClient,
    *,
    data_type: AttributeDataType,
    attribute_name: AttributeName,
    previous_prompt: str,
    current_value: str,
    improvement: str,
    image_urls: list[str] | None = None,
    session_id: str | None = None,
) -> RevisedPrompt:
    """Calibrate ``previous_prompt`` with the user's improvement into a new generation prompt."""
    revision_prompt = prompts.revise_generation_prompt(
        data_type=data_type,
        attribute_name=attribute_name,
        previous_prompt=previous_prompt,
        current_value=current_value,
        improvement=improvement,
    )
    parsed = client.call_tool(
        revision_prompt,
        model=settings.openrouter_prompt_model,
        tool=tools.REVISE_PROMPT_TOOL,
        image_urls=image_urls or None,
        session_id=session_id,
    )
    prompt = parsed.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Prompt revision returned an empty prompt")
    return RevisedPrompt(prompt=prompt.strip())


def regenerate_image(
    client: OpenRouterClient,
    ctx: GenerationContext,
    *,
    image_prompt: str,
    aspect_ratio: str,
    current_image_url: str,
    session_id: str | None = None,
) -> ImageGeneration:
    """Re-render with the revised prompt, using the current output as a primary reference."""
    image_prompt = prompts.ensure_image_render_suffix(image_prompt)
    references = [
        ReferenceImage(
            url=current_image_url,
            label=(
                "CURRENT OUTPUT — the image the user wants improved. Preserve product identity "
                "and overall composition unless the revised prompt explicitly changes them."
            ),
        ),
        *_references(ctx),
    ]
    model = settings.openrouter_image_model
    render_fn = resolve_image_model(model)

    # GPT Images API ignores per-reference labels; fold role context into the prompt.
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
            prompt=image_prompt,
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
        prompt=image_prompt,
    )


def regenerate_text(
    client: OpenRouterClient,
    *,
    name: AttributeName,
    revised_prompt: str,
    session_id: str | None = None,
) -> TextRegeneration:
    """Generate a single text attribute from the revised prompt via a forced tool call.

    Soft length targets are on the tool; hard char caps are fitted after the call.
    """
    tool = tools.text_attributes_tool([name])
    parsed = client.call_tool(
        revised_prompt,
        model=settings.openrouter_text_model,
        tool=tool,
        session_id=session_id,
    )
    raw = parsed.get(name.value)
    if raw is None:
        raise ValueError(f"Text regeneration missing attribute: {name.value}")
    fitted = tools.apply_text_limits(name, raw)
    # List attributes persist as JSON arrays (same storage form as first generation).
    if name in tools.LIST_TEXT_ATTRIBUTES:
        value = json.dumps(fitted if isinstance(fitted, list) else [], ensure_ascii=False)
    else:
        value = str(fitted)
    return TextRegeneration(value=value, prompt=revised_prompt)
