"""Text attribute generation — Category-Intelligence-led strategy, then one unified text call."""

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
    prompt: str  # the final text-generation prompt that produced the values


def generate_attributes(
    client: OpenRouterClient,
    ctx: GenerationContext,
    names: list[AttributeName],
) -> TextGeneration:
    """Generate all requested text attributes and return them with the prompt used.

    Step 1 derives a content strategy from the Category Intelligence + product angle. Step 2 writes
    all attributes at once via a forced tool call (structured args, not free-form JSON text).
    """
    strategy = client.generate_text(
        prompts.text_strategy_prompt(ctx, names), model=settings.openrouter_prompt_model
    )
    generation_prompt = prompts.text_generation_prompt(ctx, names, strategy)
    parsed = client.call_tool(
        generation_prompt,
        model=settings.openrouter_text_model,
        tool=tools.text_attributes_tool(names),
    )

    keys = [name.value for name in names]
    missing = [key for key in keys if key not in parsed]
    if missing:
        raise ValueError(f"Text generation missing attributes: {missing}")
    return TextGeneration(values={key: parsed[key] for key in keys}, prompt=generation_prompt)
