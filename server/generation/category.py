"""Task-aware distillation of the Category Intelligence file.

The full file is large (summary + lexicon + voice-of-customer + a per-topic playbook). We never
dump it wholesale into a model. For a given generation task we extract only the relevant topics
and the highest-signal keywords/customer signals, keeping the context concise and on-point.
"""

from typing import Any

from entities.catalog.attribute_enums import AttributeName

# Category Intelligence ``topics`` entries that inform each text attribute.
# Missing topic names degrade gracefully (skipped in _build), so an attribute may
# list a topic before the external scraping pipeline starts producing it.
#
# ITEM_HIGHLIGHTS has no dedicated topic yet: the scraper reads desktop pages,
# where Amazon currently merges competitor Item Highlights into the title after
# a " | " separator, and the raw titles are distilled away before they reach
# category_intelligence. Until the pipeline adds an "item_highlights" topic
# (listed first below so it wins as soon as it exists), the field draws on
# "specs" (materials/dimensions/pack facts) and "bullets" (winning benefit
# angles) — the same content Amazon says belongs in the field.
_TEXT_TOPICS_BY_ATTRIBUTE: dict[AttributeName, tuple[str, ...]] = {
    AttributeName.TITLE: ("title",),
    AttributeName.ITEM_HIGHLIGHTS: ("item_highlights", "specs", "bullets"),
    AttributeName.BULLET_POINTS: ("bullets",),
    AttributeName.DESCRIPTION: ("aplus",),
    AttributeName.BACKEND_KEYWORDS: ("keywords",),
}
# Cross-cutting topics that help all text listing optimization.
_TEXT_COMMON_TOPICS = ("keywords", "specs")
# Topics that inform every image generation call.
_IMAGE_COMMON_TOPICS = ("gallery_images",)
# Category Intelligence topics that inform image generation only when that type is requested.
# "aplus" carries the A+ module's own structural guidance (brand story -> feature callouts ->
# performance modules -> comparison chart), distinct from the main PDP gallery arc in
# "gallery_images" — pulling it in for every gallery plan would waste tokens on jobs that never
# request an A_PLUS image.
_IMAGE_TOPIC_BY_ATTRIBUTE: dict[AttributeName, str] = {
    AttributeName.A_PLUS: "aplus",
}

_MAX_KEYWORDS = 20
_MAX_SIGNALS = 12


def text_brief(category_intelligence: dict[str, Any], names: list[AttributeName]) -> dict[str, Any]:
    """Concise brief for the requested text attributes."""
    topics = [
        topic for name in names for topic in _TEXT_TOPICS_BY_ATTRIBUTE.get(name, ())
    ]
    topics.extend(_TEXT_COMMON_TOPICS)
    return _build(category_intelligence, topics)


def image_brief(category_intelligence: dict[str, Any], names: list[AttributeName]) -> dict[str, Any]:
    """Concise brief for image generation (gallery/image guidance), plus any type-specific topic
    (e.g. "aplus") only for the image types actually requested."""
    topics = list(_IMAGE_COMMON_TOPICS)
    topics.extend(
        _IMAGE_TOPIC_BY_ATTRIBUTE[name] for name in names if name in _IMAGE_TOPIC_BY_ATTRIBUTE
    )
    return _build(category_intelligence, topics)


def _build(category_intelligence: dict[str, Any], topic_names: list[str]) -> dict[str, Any]:
    topics_by_name = {t.get("name"): t for t in category_intelligence.get("topics", [])}
    playbook = {
        name: {
            "observations": topics_by_name[name].get("observations", ""),
            "actions": topics_by_name[name].get("actions", []),
        }
        for name in _dedupe(topic_names)
        if name in topics_by_name
    }

    meta = category_intelligence.get("meta", {})
    return {
        "category": meta.get("category"),
        "marketplace": meta.get("marketplace"),
        "summary": category_intelligence.get("summary") or "",
        "playbook": playbook,
        "high_value_keywords": _high_value_keywords(category_intelligence),
        "customer_signals": _customer_signals(category_intelligence),
    }


def _high_value_keywords(category_intelligence: dict[str, Any]) -> list[str]:
    terms = category_intelligence.get("category_lexicon", {}).get("terms", [])
    high = [t["term"] for t in terms if t.get("relevance") == "high" and t.get("term")]
    return high[:_MAX_KEYWORDS]


def _customer_signals(category_intelligence: dict[str, Any]) -> list[dict[str, Any]]:
    signals = category_intelligence.get("voice_of_customer", {}).get("signals", [])
    high = [
        {"phrase": s["phrase"], "sentiment": s.get("sentiment")}
        for s in signals
        if s.get("relevance") == "high" and s.get("phrase")
    ]
    return high[:_MAX_SIGNALS]


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
