"""Stage 2: render one planned image against the real product reference."""

from dataclasses import dataclass
from pathlib import Path

from core.clients.openrouter import GeneratedImage, OpenRouterClient, ReferenceImage
from core.config import settings
from entities.catalog.attribute_enums import AttributeName
from generation.context import GenerationContext
from utils import files

_PRODUCT_LABEL = (
    "PRODUCT REFERENCE {index} of {total} — the real product, this angle/closeup. Cross-reference "
    "all {total} of these together as one product; reproduce its colour, shape, material, pattern "
    "and packaging exactly; do not invent a different product."
)

# Aspect ratios each provider's Images API actually accepts. The caller (services.job) supplies a
# fixed per-image-type ratio — NOT an AI-chosen one — but if it isn't in the provider's set it can't
# be sent as-is: gpt-image-1 400s on an unrecognised ratio, and Gemini silently ignores one. So the
# supplied ratio is snapped to the nearest supported ratio by value (w/h).
_GPT_ASPECT_RATIOS = ("1:1", "3:2", "2:3")
_GEMINI_ASPECT_RATIOS = (
    "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"
)


@dataclass(frozen=True, slots=True)
class ImageGeneration:
    path: Path
    prompt: str  # the image-generation prompt actually sent to the image model


def render(
    client: OpenRouterClient,
    ctx: GenerationContext,
    image_prompt: str,
    name: AttributeName,
    slot: int,
    images_dir: Path,
    aspect_ratio: str | None = None,
) -> ImageGeneration:
    """Render one planned image with product references; return path + prompt.

    ``aspect_ratio`` is the fixed per-image-type ratio chosen by the caller (never AI-chosen); it is
    snapped to the nearest Gemini-supported ratio and sent as the API's canvas control. Whatever the
    model returns is written straight to disk — no post-processing.
    """
    image = client.generate_gemini_image(
        image_prompt,
        model=settings.openrouter_image_model,
        references=_references(ctx) or None,
        aspect_ratio=_normalize_aspect_ratio(aspect_ratio, _GEMINI_ASPECT_RATIOS),
    )
    path = _write_image(image, images_dir / f"{name.value}_{slot}")
    return ImageGeneration(path=path, prompt=image_prompt)


def render_gpt(
    client: OpenRouterClient,
    ctx: GenerationContext,
    image_prompt: str,
    name: AttributeName,
    slot: int,
    images_dir: Path,
    aspect_ratio: str | None = None,
) -> ImageGeneration:
    """Render the same planned prompt via OpenAI's gpt-image-1, for side-by-side comparison
    against ``render()``'s Gemini output. Writes a ``_gpt`` suffixed file so it never collides
    with the Gemini output for the same (name, slot).

    gpt-image-1 only accepts ``aspect_ratio`` in ``{"1:1", "3:2", "2:3", "auto"}`` — confirmed
    live against the real API; anything else 400s. The caller's fixed per-type ratio is therefore
    snapped to the nearest of those before the call. Whatever the model returns is written straight
    to disk — no post-processing.
    """
    image = client.generate_gpt_image(
        image_prompt,
        model=settings.openrouter_gpt_image_model,
        references=_references(ctx) or None,
        aspect_ratio=_normalize_aspect_ratio(aspect_ratio, _GPT_ASPECT_RATIOS),
    )
    path = _write_image(image, images_dir / f"{name.value}_{slot}_gpt")
    return ImageGeneration(path=path, prompt=image_prompt)


def _write_image(image: GeneratedImage, path_stem: Path) -> Path:
    """Write the model's image exactly as returned, choosing the extension from its content type."""
    extension = files.extension_for_image_content_type(image.content_type)
    files.ensure_dir(path_stem.parent)
    return files.write_bytes(path_stem.with_name(path_stem.name + extension), image.content)


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
