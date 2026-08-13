"""Text attribute generation — Category-Intelligence-led strategy, then one attribute at a time."""

from __future__ import annotations

import json
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
    prompt: str  # full generation prompt as sent to the model (draft brief)


def generate_attribute(
    client: OpenRouterClient,
    ctx: GenerationContext,
    name: AttributeName,
    *,
    session_id: str | None = None,
) -> TextGeneration:
    """Generate a single text attribute and return its value with the as-sent generation prompt.

    Step 1 derives a content strategy for this attribute. Step 2 drafts via a forced tool call
    (no schema ``maxLength``). Step 3 validates Amazon hard caps in code; if over, a rewrite
    tool call (with ``maxLength``) asks the model to shorten. Shared context is cacheable.
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
    return _generate_via_tool(client, name, generation_parts, session_id=session_id)


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
    Same draft → validate → rewrite length gate as other text attributes.
    """
    name = AttributeName.KEY_FEATURES
    generation_parts = prompts.key_features_parts(
        ctx, description=description, bullet_points=bullet_points
    )
    return _generate_via_tool(client, name, generation_parts, session_id=session_id)


# Total attempts for the length correction loop (1 initial + N corrections).
_MAX_LENGTH_ATTEMPTS = 3
# Aim below the hard cap so natural variance stays under it.
_SOFT_TARGET_RATIO = 0.9


def submit_text_attribute(
    client: OpenRouterClient,
    *,
    name: AttributeName,
    prompt: str,
    cache_prefix: str | None = None,
    session_id: str | None = None,
) -> Any:
    """Generate text via a forced tool call, enforcing Amazon character caps in code.

    The schema never sets ``maxLength`` (that causes constrained-decoding mid-word cuts).
    Instead we validate lengths and, if any string is over, re-call the model targeting ONLY
    the over-limit strings with a concrete cut target, then keep the shorter of the previous
    and new version per item (monotonic merge) so passing items never regress. Bounded by
    ``_MAX_LENGTH_ATTEMPTS``. Used by both generation and regeneration; never truncates copy.
    """
    key = name.value
    tool = tools.text_attributes_tool([name])
    is_list = name in tools.LIST_TEXT_ATTRIBUTES

    parsed = client.call_tool(
        prompt,
        model=settings.openrouter_text_model,
        tool=tool,
        cache_prefix=cache_prefix,
        session_id=session_id,
    )
    if key not in parsed:
        raise ValueError(f"Text generation missing attribute: {key}")
    value: Any = parsed[key]

    for _ in range(_MAX_LENGTH_ATTEMPTS - 1):
        report = tools.over_limit_report(name, value)
        if not report:
            return value

        correction = prompts.text_length_correction(
            name,
            _format_value_for_prompt(name, value),
            [_cut_instruction(issue) for issue in report],
            is_list=is_list,
        )
        parsed = client.call_tool(
            f"{prompt}\n\n{correction}",
            model=settings.openrouter_text_model,
            tool=tool,
            session_id=session_id,
        )
        if key not in parsed:
            raise ValueError(f"Text length correction missing attribute: {key}")
        value = _merge_shorter(name, value, parsed[key])

    remaining = tools.char_limit_violations(name, value)
    if remaining:
        detail = "; ".join(remaining)
        raise ValueError(
            f"Text for {key} still exceeds character limits after "
            f"{_MAX_LENGTH_ATTEMPTS} attempts: {detail}"
        )
    return value


def _cut_instruction(issue: tools.LengthIssue) -> str:
    target = int(issue.max_chars * _SOFT_TARGET_RATIO)
    label = "value" if issue.index is None else f"item {issue.index + 1}"
    return (
        f"{label}: {issue.length} chars — remove at least {issue.excess} to get under "
        f"{issue.max_chars}; aim for ~{target} and end on a complete word"
    )


def _merge_shorter(name: AttributeName, current: Any, candidate: Any) -> Any:
    """Keep the shorter string per position so over-limit items shrink and others hold."""
    if name in tools.LIST_TEXT_ATTRIBUTES:
        if not isinstance(current, list) or not isinstance(candidate, list):
            return candidate if isinstance(candidate, list) else current
        merged = list(current)
        for index, item in enumerate(current):
            if index < len(candidate):
                new_item = candidate[index]
                if isinstance(new_item, str) and len(new_item) < len(str(item)):
                    merged[index] = new_item
        return merged
    if isinstance(candidate, str) and isinstance(current, str):
        return candidate if len(candidate) < len(current) else current
    return candidate


def _generate_via_tool(
    client: OpenRouterClient,
    name: AttributeName,
    generation_parts: prompts.PromptParts,
    *,
    session_id: str | None,
) -> TextGeneration:
    """Draft + length gate; persist the original generation brief as the stored prompt."""
    value = submit_text_attribute(
        client,
        name=name,
        prompt=generation_parts.suffix,
        cache_prefix=generation_parts.prefix,
        session_id=session_id,
    )
    return TextGeneration(values={name.value: value}, prompt=generation_parts.as_sent())


def _format_value_for_prompt(name: AttributeName, value: Any) -> str:
    if name in tools.LIST_TEXT_ATTRIBUTES:
        return json.dumps(value if isinstance(value, list) else [], ensure_ascii=False)
    return str(value)
