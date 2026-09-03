"""Stage 2: render one planned image against the real product reference."""

from collections.abc import Callable
from dataclasses import dataclass

from core.clients.openrouter import OpenRouterClient, ReferenceImage
from core.config import settings
from entities.catalog.attribute_enums import AttributeName
from pipelines.generation.context import GenerationContext

_PRODUCT_LABEL = (
    "PRODUCT REFERENCE {index} of {total} — the real product, this angle/closeup. Cross-reference "
    "all {total} of these together as one product; reproduce its colour, shape, material, pattern "
    "and packaging exactly; do not invent a different product. Do not copy printed text, badges, "
    "size tags, or overlays from this photo — those are not on-image claims to paint."
)

# Aspect ratios each provider accepts. The caller (services.job) supplies a fixed per-image-type
# ratio — NOT an AI-chosen one — snapped to the nearest supported ratio by value (w/h).
_GEMINI_ASPECT_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")
_GPT_ASPECT_RATIOS = ("1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16", "21:9")


@dataclass(frozen=True, slots=True)
class ImageGeneration:
    """In-memory image bytes from the model — caller uploads to GCS."""

    content: bytes
    content_type: str
    prompt: str


# Model ID from OPENROUTER_IMAGE_MODEL → render fn.
# Swap the env model ID to compare; prompt planning stays the same for every path.
RenderFn = Callable[
    [OpenRouterClient, GenerationContext, str, AttributeName, int, str | None, str | None],
    ImageGeneration,
]


def render(
    client: OpenRouterClient,
    ctx: GenerationContext,
    image_prompt: str,
    _name: AttributeName,
    _slot: int,
    aspect_ratio: str | None = None,
    session_id: str | None = None,
) -> ImageGeneration:
    """Render one planned image via Gemini (chat + modalities)."""
    sent = image_prompt.strip()
    image = client.generate_gemini_image(
        sent,
        model=settings.openrouter_image_model,
        references=_references(ctx) or None,
        aspect_ratio=_normalize_aspect_ratio(aspect_ratio, _GEMINI_ASPECT_RATIOS),
        session_id=session_id,
    )
    return ImageGeneration(
        content=image.content,
        content_type=image.content_type,
        prompt=sent,
    )


def render_gpt(
    client: OpenRouterClient,
    ctx: GenerationContext,
    image_prompt: str,
    _name: AttributeName,
    _slot: int,
    aspect_ratio: str | None = None,
    session_id: str | None = None,
) -> ImageGeneration:
    """Render the same planned prompt via GPT Image (dedicated Images API)."""
    sent = image_prompt.strip()
    image = client.generate_gpt_image(
        sent,
        model=settings.openrouter_image_model,
        references=_references(ctx) or None,
        aspect_ratio=_normalize_aspect_ratio(aspect_ratio, _GPT_ASPECT_RATIOS),
        session_id=session_id,
    )
    return ImageGeneration(
        content=image.content,
        content_type=image.content_type,
        prompt=sent,
    )


# Known image models → which render path to use.
IMAGE_MODELS: dict[str, RenderFn] = {
    "google/gemini-3-pro-image": render,
    "openai/gpt-image-2": render_gpt,
}


def resolve_image_model(model: str) -> RenderFn:
    """Map ``OPENROUTER_IMAGE_MODEL`` to the matching render function."""
    try:
        return IMAGE_MODELS[model]
    except KeyError:
        known = ", ".join(sorted(IMAGE_MODELS))
        raise ValueError(
            f"Unknown openrouter_image_model={model!r}; expected one of: {known}"
        ) from None


def _normalize_aspect_ratio(requested: str | None, allowed: tuple[str, ...]) -> str:
    """Snap a requested ``"w:h"`` ratio to the nearest ratio the provider supports (by w/h value).

    Falls back to ``"1:1"`` when the ratio is missing or unparseable, so a bad/omitted value never
    reaches the API as an unsupported string.
    """
    if requested in allowed:
        return requested
    target = _aspect_value(requested)
    if target is None:
        return "1:1"
    return min(allowed, key=lambda ratio: abs((_aspect_value(ratio) or 1.0) - target))


def _aspect_value(ratio: str | None) -> float | None:
    """``"3:2"`` -> ``1.5``; ``None``/malformed/zero-height -> ``None``."""
    if not ratio or ":" not in ratio:
        return None
    width, _, height = ratio.partition(":")
    try:
        width_f, height_f = float(width), float(height)
    except ValueError:
        return None
    return width_f / height_f if height_f else None


def _references(ctx: GenerationContext) -> list[ReferenceImage]:
    """Product source images as visual truth.

    Every reference is labelled with its position (e.g. "2 of 8") so the model treats the set as
    multiple angles of one product, not a single photo repeated or a series of unrelated ones.
    """
    total = len(ctx.product_image_urls)
    return [
        ReferenceImage(url=url, label=_PRODUCT_LABEL.format(index=index, total=total))
        for index, url in enumerate(ctx.product_image_urls, start=1)
    ]
