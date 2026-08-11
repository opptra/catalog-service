"""Text attribute generation — Category-Intelligence-led strategy, then one attribute at a time."""

from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from entities.catalog.attribute_enums import AttributeName
from generation import prompts, tools
from generation.context import GenerationContext


@dataclass(frozen=True, slots=True)
class TextGeneration:
    values: dict[str, Any]
    prompt: str  # full generation prompt as sent to the model


def generate_attribute(
    client: OpenRouterClient,
    ctx: GenerationContext,
    name: AttributeName,
    *,
    session_id: str | None = None,
) -> TextGeneration:
    """Generate a single text attribute and return its value with the as-sent generation prompt.

    Step 1 derives a content strategy for this attribute. Step 2 writes the attribute via a forced
    tool call. Shared product/brand/rules context is sent as a cacheable prefix when supported.
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
    parsed = client.call_tool(
        generation_parts.suffix,
        model=settings.openrouter_text_model,
        tool=tools.text_attributes_tool(names),
        cache_prefix=generation_parts.prefix,
        session_id=session_id,
    )

    key = name.value
    if key not in parsed:
        raise ValueError(f"Text generation missing attribute: {key}")
    return TextGeneration(
        values={key: parsed[key]},
        prompt=generation_parts.as_sent(),
    )
