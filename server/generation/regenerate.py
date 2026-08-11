"""Regenerate a single attribute value from user improvement notes.

Flow: load previous prompt + current value → revise prompt → re-render (image or text)
→ persist a new version under the same value ``external_id``.
"""

import json
import logging
from dataclasses import dataclass

from core.clients.openrouter import OpenRouterClient, ReferenceImage
from core.config import settings
from entities.catalog.attribute_enums import AttributeDataType, AttributeName
from generation import prompts, tools
from generation.context import GenerationContext
from generation.images import (
    ImageGeneration,
    _GEMINI_ASPECT_RATIOS,
    _GPT_ASPECT_RATIOS,
    _normalize_aspect_ratio,
    _references,
    resolve_image_model,
)

logger = logging.getLogger(__name__)


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
) -> ImageGeneration:
    """Re-render with the revised prompt, using the current output as a primary reference."""
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
) -> TextRegeneration:
    """Generate a single text attribute from the revised prompt via a forced tool call.

    Enforces the same TEXT_LIMITS as first generation: one repair retry with the
    exact violations, then minimum-length misses are accepted with a warning while
    Amazon maximums stay hard.
    """
    limit_sentence = tools.limit_sentence(name)
    base_prompt = (
        revised_prompt if limit_sentence is None else f"{revised_prompt}\n\n{limit_sentence}"
    )
    tool = tools.text_attributes_tool([name])
    prompt_text = base_prompt
    raw = None
    violations: list[tools.Violation] = []
    for _attempt in range(2):
        parsed = client.call_tool(
            prompt_text,
            model=settings.openrouter_text_model,
            tool=tool,
        )
        raw = parsed.get(name.value)
        if raw is None:
            raise ValueError(f"Text regeneration missing attribute: {name.value}")
        violations = tools.validate_text_value(name, raw)
        if not violations:
            break
        prompt_text = (
            f"{base_prompt}\n\n"
            "YOUR PREVIOUS ATTEMPT FAILED THESE CHECKS:\n"
            + "\n".join(f"- {violation.message}" for violation in violations)
            + "\nRewrite to satisfy every check and resubmit via the tool."
        )
    if violations:
        if all(violation.is_minimum for violation in violations):
            logger.warning(
                "Accepting regenerated %s below minimum after retry: %s",
                name.value,
                tools.violation_messages(violations),
            )
        else:
            raise ValueError(
                "Text regeneration violated limits after retry: "
                f"{tools.violation_messages(violations)}"
            )
    # List attributes persist as JSON arrays (same storage form as first generation).
    if name in tools.LIST_TEXT_ATTRIBUTES:
        value = json.dumps(raw if isinstance(raw, list) else [], ensure_ascii=False)
    else:
        value = str(raw)
    return TextRegeneration(value=value, prompt=revised_prompt)
