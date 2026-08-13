"""Regenerate a single attribute value from user improvement notes.

Flow: keep the stored previous prompt as the brief → send it with the current
value/image and the user note into one generate call → persist a new version
under the same value ``external_id``. Does not invent a replacement prompt.

Text regeneration uses the same draft → validate → model-rewrite length gate as
initial generation (see ``generation.text.submit_text_attribute``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from core.clients.openrouter import OpenRouterClient, ReferenceImage
from core.config import settings
from entities.catalog.attribute_enums import AttributeName
from generation import prompts, tools
from generation.context import GenerationContext
from generation.images import (
    _GEMINI_ASPECT_RATIOS,
    _GPT_ASPECT_RATIOS,
    ImageGeneration,
    _normalize_aspect_ratio,
    _references,
    resolve_image_model,
)
from generation.text import submit_text_attribute

_TEXT_IDENTICAL_RETRIES = 1


@dataclass(frozen=True, slots=True)
class TextRegeneration:
    value: str
    prompt: str


def regenerate_image(
    client: OpenRouterClient,
    ctx: GenerationContext,
    *,
    previous_prompt: str,
    improvement: str,
    aspect_ratio: str,
    current_image_url: str,
    attribute_name: AttributeName,
) -> ImageGeneration:
    """Re-render from the stored brief + user note, with current output as primary reference."""
    image_prompt = prompts.ensure_image_render_suffix(
        prompts.regeneration_image_prompt(
            attribute_name=attribute_name,
            previous_prompt=previous_prompt,
            improvement=improvement,
        )
    )
    references = [
        ReferenceImage(
            url=current_image_url,
            label=(
                "CURRENT OUTPUT — the image the user wants improved. Preserve product identity "
                "and overall composition unless the user improvement explicitly changes them."
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
        )
        return ImageGeneration(
            content=image.content,
            content_type=image.content_type,
            prompt=prompts.prompt_with_user_edit(previous_prompt, improvement),
        )

    image = client.generate_gemini_image(
        image_prompt,
        model=model,
        references=references,
        aspect_ratio=_normalize_aspect_ratio(aspect_ratio, _GEMINI_ASPECT_RATIOS),
    )
    return ImageGeneration(
        content=image.content,
        content_type=image.content_type,
        prompt=prompts.prompt_with_user_edit(previous_prompt, improvement),
    )


def regenerate_text(
    client: OpenRouterClient,
    *,
    name: AttributeName,
    previous_prompt: str,
    current_value: str,
    improvement: str,
) -> TextRegeneration:
    """Regenerate text from the stored brief + current value + user note.

    Retries once if the draft (before length rewrite) is identical to CURRENT OUTPUT.
    Length enforcement always goes through ``submit_text_attribute`` (same as generation).
    """
    call_prompt = prompts.regeneration_text_prompt(
        attribute_name=name,
        previous_prompt=previous_prompt,
        current_value=current_value,
        improvement=improvement,
    )
    stored_prompt = prompts.prompt_with_user_edit(previous_prompt, improvement)

    last_value: str | None = None
    attempts = 1 + _TEXT_IDENTICAL_RETRIES
    for attempt in range(attempts):
        prompt = call_prompt
        if attempt > 0:
            prompt = (
                f"{call_prompt}\n\n"
                "CRITICAL: Your previous result was identical to CURRENT OUTPUT. "
                "You must apply the USER IMPROVEMENT so the new value is visibly different."
            )
        raw = submit_text_attribute(client, name=name, prompt=prompt)
        if name in tools.LIST_TEXT_ATTRIBUTES:
            value = json.dumps(raw if isinstance(raw, list) else [], ensure_ascii=False)
        else:
            value = str(raw)
        last_value = value
        if not _text_values_equal(name, value, current_value):
            return TextRegeneration(value=value, prompt=stored_prompt)

    assert last_value is not None
    return TextRegeneration(value=last_value, prompt=stored_prompt)


def _text_values_equal(name: AttributeName, left: str, right: str) -> bool:
    if name in tools.LIST_TEXT_ATTRIBUTES:
        try:
            return json.loads(left) == json.loads(right)
        except json.JSONDecodeError:
            return left.strip() == right.strip()
    return left.strip() == right.strip()
