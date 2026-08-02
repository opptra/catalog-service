"""Stage 2: render one planned image against the real product reference (and brand logo)."""

from dataclasses import dataclass
from pathlib import Path

from core.clients.openrouter import OpenRouterClient, ReferenceImage
from core.config import settings
from entities.catalog.attribute_enums import AttributeName
from generation.context import GenerationContext
from utils import files

_PRODUCT_LABEL = (
    "PRODUCT REFERENCE — the real product. Reproduce its colour, shape, material, pattern and "
    "packaging exactly; do not invent a different product."
)
_LOGO_LABEL = (
    "BRAND LOGO asset — include it on this image, composited small, undistorted and "
    "non-intrusive; never let it cover the product's focal details."
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
    aspect_ratio: str = "1:1",
) -> ImageGeneration:
    """Render one planned image with product + logo references; return path + prompt.

    ``aspect_ratio`` is fixed at ``"1:1"`` for now; the planner already emits a per-slot ratio that
    can be wired in here later for dynamic shapes.
    """
    image = client.generate_gemini_image(
        image_prompt,
        model=settings.openrouter_image_model,
        references=_references(ctx) or None,
        aspect_ratio=aspect_ratio,
    )
    extension = files.extension_for_image_content_type(image.content_type)
    files.ensure_dir(images_dir)
    path = files.write_bytes(images_dir / f"{name.value}_{slot}{extension}", image.content)
    return ImageGeneration(path=path, prompt=image_prompt)


def render_gpt(
    client: OpenRouterClient,
    ctx: GenerationContext,
    image_prompt: str,
    name: AttributeName,
    slot: int,
    images_dir: Path,
    aspect_ratio: str = "1:1",
) -> ImageGeneration:
    """Render the same planned prompt via OpenAI's gpt-image-1, for side-by-side comparison
    against ``render()``'s Gemini output. Writes a ``_gpt`` suffixed file so it never collides
    with the Gemini output for the same (name, slot).

    gpt-image-1 only accepts ``aspect_ratio`` in ``{"1:1", "3:2", "2:3", "auto"}`` — confirmed
    live against the real API; anything else 400s (unlike Gemini's much wider set).
    """
    image = client.generate_gpt_image(
        image_prompt,
        model=settings.openrouter_gpt_image_model,
        references=_references(ctx) or None,
        aspect_ratio=aspect_ratio,
    )
    extension = files.extension_for_image_content_type(image.content_type)
    files.ensure_dir(images_dir)
    path = files.write_bytes(images_dir / f"{name.value}_{slot}_gpt{extension}", image.content)
    return ImageGeneration(path=path, prompt=image_prompt)


def _references(ctx: GenerationContext) -> list[ReferenceImage]:
    """Product source image(s) as visual truth, plus the brand logo as an available asset."""
    references = [ReferenceImage(url=url, label=_PRODUCT_LABEL) for url in ctx.product_image_urls]
    if ctx.brand_logo_url:
        references.append(ReferenceImage(url=ctx.brand_logo_url, label=_LOGO_LABEL))
    return references
