"""Task-aware distillation of the Category Intelligence file.

The full file is large (summary + lexicon + voice-of-customer + a per-topic playbook + image_plan).
We never dump it wholesale into a model. For a given generation task we extract only the relevant
topics, the highest-signal keywords/customer signals, and (for images) a core-first role palette
from ``image_plan``, keeping the context concise and on-point.
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
# Topics that inform every image generation call (supporting context only when image_plan exists).
_IMAGE_COMMON_TOPICS = ("gallery_images",)
# Category Intelligence topics that inform image generation only when that type is requested.
# "aplus" carries the A+ module's own structural guidance (brand story -> feature callouts ->
# performance modules -> comparison chart), distinct from the main PDP gallery arc in
# "gallery_images" — pulling it in for every gallery plan would waste tokens on jobs that never
# request an A_PLUS image.
_IMAGE_TOPIC_BY_ATTRIBUTE: dict[AttributeName, str] = {
    AttributeName.A_PLUS: "aplus",
}
# CI schema 2.4+ ``image_plan`` tracks → attribute. Primary role palette for the gallery planner.
_IMAGE_PLAN_TRACK_BY_ATTRIBUTE: dict[AttributeName, str] = {
    AttributeName.IMAGE: "gallery",
    AttributeName.A_PLUS: "aplus",
}
_IMAGE_PLAN_SLOT_FIELDS = (
    "order",
    "priority",
    "role",
    "kind",
    "pattern",
    "content",
    # Slot-level duplication + feature budget contract for selection/prompting.
    "owns",
    "feature_priority",
    "max_callouts",
)

_MAX_KEYWORDS = 20
_MAX_SIGNALS = 12


def text_brief(category_intelligence: dict[str, Any], names: list[AttributeName]) -> dict[str, Any]:
    """Concise brief for the requested text attributes."""
    topics = [topic for name in names for topic in _TEXT_TOPICS_BY_ATTRIBUTE.get(name, ())]
    topics.extend(_TEXT_COMMON_TOPICS)
    return _build(category_intelligence, topics)


def image_brief(
    category_intelligence: dict[str, Any], names: list[AttributeName]
) -> dict[str, Any]:
    """Concise brief for image generation: distilled ``image_plan`` (primary role palette when
    present) plus supporting topic playbook for the image types actually requested."""
    topics = list(_IMAGE_COMMON_TOPICS)
    topics.extend(
        _IMAGE_TOPIC_BY_ATTRIBUTE[name] for name in names if name in _IMAGE_TOPIC_BY_ATTRIBUTE
    )
    brief = _build(category_intelligence, topics)
    plan = _distill_image_plan(category_intelligence, names)
    if plan:
        brief["image_plan"] = plan
    return brief


def _distill_image_plan(
    category_intelligence: dict[str, Any], names: list[AttributeName]
) -> dict[str, Any] | None:
    """Core-first role palette from CI ``image_plan`` for each requested IMAGE/A_PLUS track.

    Returns None when the CI file has no usable ``image_plan`` (older schemas still work via
    topic playbook alone).
    """
    raw = category_intelligence.get("image_plan")
    if not isinstance(raw, dict):
        return None

    out: dict[str, Any] = {}
    for name in _dedupe([n for n in names if n in _IMAGE_PLAN_TRACK_BY_ATTRIBUTE]):
        track_key = _IMAGE_PLAN_TRACK_BY_ATTRIBUTE[name]
        track = raw.get(track_key)
        distilled = _distill_image_plan_track(track)
        if distilled is not None:
            out[name.value] = distilled
    return out or None


def _distill_image_plan_track(track: Any) -> dict[str, Any] | None:
    """Compact one gallery/aplus track: rationale + core-then-extended slot palette."""
    if not isinstance(track, dict):
        return None

    slots_raw = track.get("slots")
    if not isinstance(slots_raw, list):
        slots_raw = []

    distilled_slots: list[dict[str, Any]] = []
    for slot in slots_raw:
        if not isinstance(slot, dict):
            continue
        entry = {
            field: slot[field] for field in _IMAGE_PLAN_SLOT_FIELDS if field in slot and slot[field]
        }
        if entry.get("role") or entry.get("kind") or entry.get("pattern"):
            distilled_slots.append(entry)

    def _order_key(s: dict[str, Any]) -> int:
        order = s.get("order")
        return order if isinstance(order, int) else 10**9

    core = sorted(
        (s for s in distilled_slots if str(s.get("priority", "")).lower() == "core"),
        key=_order_key,
    )
    extended = sorted(
        (s for s in distilled_slots if str(s.get("priority", "")).lower() != "core"),
        key=_order_key,
    )
    # Core first (primary ideas), then extended — full palette; planner picks to length N.
    slots = core + extended

    distilled: dict[str, Any] = {"slots": slots}
    if "recommended_build" in track:
        distilled["recommended_build"] = track["recommended_build"]
    if track.get("build_rationale"):
        distilled["build_rationale"] = track["build_rationale"]
    if track.get("visual_norms"):
        distilled["visual_norms"] = track["visual_norms"]
    # Empty slots with no rationale is useless — treat as missing track.
    if not slots and "recommended_build" not in distilled and "build_rationale" not in distilled:
        return None
    return distilled


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
