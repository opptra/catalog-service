"""Text attribute generation — Category-Intelligence-led strategy, then one attribute at a time."""

import logging
from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from entities.catalog.attribute_enums import AttributeName
from generation import prompts, tools
from generation.context import GenerationContext

logger = logging.getLogger(__name__)


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
    return _generate_validated(client, name, generation_parts, session_id=session_id)


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
    return _generate_validated(client, name, generation_parts, session_id=session_id)


# One repair attempt after the first validation failure: the model gets the exact
# violations back and rewrites. Providers do not reliably enforce schema
# minLength/maxLength on tool arguments, so occasional misses are expected —
# a single feedback round fixes most of them without an unbounded loop.
_REPAIR_ATTEMPTS = 1


def _generate_validated(
    client: OpenRouterClient,
    name: AttributeName,
    generation_parts: prompts.PromptParts,
    *,
    session_id: str | None,
) -> TextGeneration:
    """Call the generation tool, validate limits, and retry once with feedback.

    After the retry, minimum-length violations (our quality floors) are accepted
    with a warning — a slightly short value beats a FAILED task. Maximums are
    Amazon hard caps and always fail.
    """
    tool = tools.text_attributes_tool([name])
    key = name.value
    suffix = generation_parts.suffix
    violations: list[tools.Violation] = []
    value: Any = None
    for _attempt in range(1 + _REPAIR_ATTEMPTS):
        parsed = client.call_tool(
            suffix,
            model=settings.openrouter_text_model,
            tool=tool,
            cache_prefix=generation_parts.prefix,
            session_id=session_id,
        )
        if key not in parsed:
            raise ValueError(f"Text generation missing attribute: {key}")
        value = parsed[key]
        violations = tools.validate_text_value(name, value)
        if not violations:
            return TextGeneration(values={key: value}, prompt=generation_parts.as_sent())
        suffix = (
            f"{generation_parts.suffix}\n\n"
            "YOUR PREVIOUS ATTEMPT FAILED THESE CHECKS:\n"
            + "\n".join(f"- {violation.message}" for violation in violations)
            + "\nRewrite to satisfy every check and resubmit via the tool."
        )
    if all(violation.is_minimum for violation in violations):
        logger.warning(
            "Accepting %s below minimum after retry: %s",
            key,
            tools.violation_messages(violations),
        )
        return TextGeneration(values={key: value}, prompt=generation_parts.as_sent())
    raise ValueError(
        f"Text generation violated limits after retry: {tools.violation_messages(violations)}"
    )
