"""Text attribute generation — fact sheet + CI craft topic; keywords filtered from CI terms."""

from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from entities.catalog.attribute_enums import AttributeName
from pipelines.generation import category, prompts, tools
from pipelines.generation.context import GenerationContext
from pipelines.generation.tools import TextLimit

_KEYWORD_FILTER_V1_BRIEF = (
    "Filter Category Intelligence backend keyword candidates against this SKU's fact sheet."
)


@dataclass(frozen=True, slots=True)
class TextGeneration:
    values: dict[str, Any]
    prompt: str  # unique brief persisted as v1 (strategy or filter note)


_KEY_FEATURES_V1_BRIEF = (
    "Condense this SKU's already-written Description and Bullet Points into Amazon "
    "Key Product Features."
)


def generate_attribute(
    client: OpenRouterClient,
    ctx: GenerationContext,
    name: AttributeName,
    *,
    limit: TextLimit | None = None,
    session_id: str | None = None,
) -> TextGeneration:
    """Generate a visible text attribute: strategy from craft topic, then write via tool."""
    strategy_parts = prompts.text_strategy_parts(ctx, name)
    strategy = client.generate_text(
        strategy_parts.suffix,
        model=settings.openrouter_text_model,
        cache_prefix=strategy_parts.prefix,
        session_id=session_id,
    )

    generation_parts = prompts.text_generation_parts(ctx, name, strategy)
    result = _generate_via_tool(client, name, generation_parts, limit=limit, session_id=session_id)
    return TextGeneration(values=result.values, prompt=strategy.strip())


def filter_backend_keywords(
    client: OpenRouterClient,
    ctx: GenerationContext,
    *,
    title: str | None = None,
    session_id: str | None = None,
) -> TextGeneration:
    """Filter CI ``backend_keywords.terms`` to terms this SKU may use."""
    name = AttributeName.BACKEND_KEYWORDS
    candidates = category.backend_keywords_candidates(ctx.category_intelligence)
    terms = candidates.get("terms") or []
    if not terms:
        return TextGeneration(values={name.value: []}, prompt=_KEYWORD_FILTER_V1_BRIEF)

    parts = prompts.keyword_filter_parts(ctx, candidates=candidates, title=title)
    tool = tools.filter_backend_keywords_tool(candidate_terms=terms)
    parsed = client.call_tool(
        parts.suffix,
        model=settings.openrouter_text_model,
        tool=tool,
        cache_prefix=parts.prefix,
        session_id=session_id,
    )
    kept = tools.validate_keyword_subset(parsed.get("terms"), terms)
    byte_limit = candidates.get("marketplace_limit_bytes")
    if isinstance(byte_limit, int):
        kept = tools.trim_terms_to_byte_limit(kept, byte_limit)
    return TextGeneration(values={name.value: kept}, prompt=_KEYWORD_FILTER_V1_BRIEF)


def generate_key_features(
    client: OpenRouterClient,
    ctx: GenerationContext,
    *,
    description: str,
    bullet_points: list[str],
    limit: TextLimit | None = None,
    session_id: str | None = None,
) -> TextGeneration:
    """Derive KEY_FEATURES from the already-generated description + bullet points."""
    name = AttributeName.KEY_FEATURES
    generation_parts = prompts.key_features_parts(
        ctx, description=description, bullet_points=bullet_points
    )
    result = _generate_via_tool(client, name, generation_parts, limit=limit, session_id=session_id)
    return TextGeneration(values=result.values, prompt=_KEY_FEATURES_V1_BRIEF)


def _generate_via_tool(
    client: OpenRouterClient,
    name: AttributeName,
    generation_parts: prompts.PromptParts,
    *,
    limit: TextLimit | None,
    session_id: str | None,
) -> TextGeneration:
    """Call the generation tool once; fit oversize copy at a phrase/word boundary."""
    limits = {name: limit} if limit is not None else None
    tool = tools.text_attributes_tool([name], limits=limits)
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
        values={key: tools.apply_text_limits(name, parsed[key], limit)},
        prompt=generation_parts.as_sent(),
    )
