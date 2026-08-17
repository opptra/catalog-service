"""Text attribute generation — Category-Intelligence-led strategy, then one attribute at a time."""

from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from entities.catalog.attribute_enums import AttributeName
from pipelines.generation import prompts, tools
from pipelines.generation.context import GenerationContext


@dataclass(frozen=True, slots=True)
class TextGeneration:
    values: dict[str, Any]
    prompt: str  # unique brief persisted as v1 (strategy, not product/brand prefix)


_KEY_FEATURES_V1_BRIEF = (
    "Condense this SKU's already-written Description and Bullet Points into Amazon "
    "Key Product Features."
)


def generate_attribute(
    client: OpenRouterClient,
    ctx: GenerationContext,
    name: AttributeName,
    *,
    session_id: str | None = None,
) -> TextGeneration:
    """Generate a single text attribute and return its value with the unique v1 brief.

    Step 1 derives a content strategy for this attribute. Step 2 writes the attribute via a forced
    tool call. Shared product/brand/rules context is sent as a cacheable prefix when supported
    and is not persisted. Soft length targets are on the tool descriptions; hard char caps are
    fitted after the call.
    """
    names = [name]
    strategy_parts = prompts.text_strategy_parts(ctx, names)
    strategy = client.generate_text(
        strategy_parts.suffix,
        model=settings.openrouter_prompt_model,
        cache_prefix=strategy_parts.prefix,
        session_id=session_id,
    )

    generation_parts = prompts.text_generation_parts(ctx, names, strategy)
    result = _generate_via_tool(client, name, generation_parts, session_id=session_id)
    return TextGeneration(values=result.values, prompt=strategy.strip())


def generate_key_features(
    client: OpenRouterClient,
    ctx: GenerationContext,
    *,
    description: str,
    bullet_points: list[str],
    session_id: str | None = None,
) -> TextGeneration:
    """Derive KEY_FEATURES from the already-generated description + bullet points.

    No strategy step: this is compression of existing copy, not fresh research.
    """
    name = AttributeName.KEY_FEATURES
    generation_parts = prompts.key_features_parts(
        ctx, description=description, bullet_points=bullet_points
    )
    result = _generate_via_tool(client, name, generation_parts, session_id=session_id)
    return TextGeneration(values=result.values, prompt=_KEY_FEATURES_V1_BRIEF)


def _generate_via_tool(
    client: OpenRouterClient,
    name: AttributeName,
    generation_parts: prompts.PromptParts,
    *,
    session_id: str | None,
) -> TextGeneration:
    """Call the generation tool once; fit oversize copy at a phrase/word boundary."""
    tool = tools.text_attributes_tool([name])
    key = name.value
    parsed = client.call_tool(
        generation_parts.suffix,
        model=settings.openrouter_text_model,
        tool=tool,
        cache_prefix=generation_parts.prefix,
        session_id=session_id,
    )
    if key not in parsed:
        raise ValueError(f"Text generation missing attribute: {key}")
    return TextGeneration(
        values={key: tools.apply_text_limits(name, parsed[key])},
        prompt=generation_parts.as_sent(),
    )
