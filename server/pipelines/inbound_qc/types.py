"""Shared value objects for inbound content QC.

CLI and a future job both pass ``SkuBundle`` into ``run_inbound_qc``.
"""

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["info", "warning", "blocker"]
FindingKind = Literal["intra_row", "intra_folder", "cross_modal", "error"]
JudgeSeverity = Literal["low", "medium", "high"]
Visibility = Literal["clear", "inferred", "not_visible", "n/a"]
Evidence = Literal["on_product", "room_context", "none"]

CONFLICT_TYPE_LABELS: dict[str, str] = {
    "intra_folder": "between images",
    "cross_modal": "between text and image",
    "intra_row": "between text",
    "error": "error",
}

PRIORITY_CERTAINTY_MIN = 80
PRIORITY_SIMILARITY_MAX = 50

# Independent 0–100 scores from bedsheet extract. Highest score wins.
BEDSHEET_TYPE_SCORE_KEYS = (
    "bedsheet",
    "duvet",
    "comforter",
    "quilt",
    "blanket",
    "duvet_cover",
)


def pick_product_type(scores: dict[str, int]) -> tuple[str, int] | None:
    """Highest independent score wins. A tie keeps bedsheet."""
    if not scores:
        return None
    winner = max(
        BEDSHEET_TYPE_SCORE_KEYS,
        key=lambda key: (scores.get(key, 0), key == "bedsheet"),
    )
    score = scores.get(winner, 0)
    if score <= 0:
        return None
    return winner, score


def format_type_scores(scores: dict[str, int]) -> str:
    ranked = sorted(
        ((key.replace("_", " "), value) for key, value in scores.items() if value > 0),
        key=lambda item: item[1],
        reverse=True,
    )
    return ", ".join(f"{name} {value}" for name, value in ranked)


def conflict_is_priority(certainty: int | None, similarity: int | None) -> bool:
    """Certain contradiction, not a high-similarity near-match."""
    if certainty is None or certainty < PRIORITY_CERTAINTY_MIN:
        return False
    if similarity is None:
        return True
    return similarity <= PRIORITY_SIMILARITY_MAX


@dataclass(frozen=True, slots=True)
class ImageRef:
    """One source photo. ``content`` is used by the CLI; ``url`` by a future GCS loader."""

    filename: str
    content: bytes | None = None
    content_type: str = "image/jpeg"
    url: str | None = None


@dataclass(frozen=True, slots=True)
class SkuBundle:
    sku_id: str
    attributes: dict[str, str]
    images: tuple[ImageRef, ...] = ()


@dataclass(frozen=True, slots=True)
class Checklist:
    """Which fact types to look for in photos. Built from CSV headers + row category."""

    visual: tuple[str, ...] = ()
    skip: tuple[str, ...] = ()
    category: str = "generic"


@dataclass(frozen=True, slots=True)
class Finding:
    sku_id: str
    severity: Severity
    kind: FindingKind
    field: str
    catalog_value: str
    observed: str
    visibility: Visibility = "n/a"
    confidence: int | None = None
    similarity: int | None = None
    image_files: str = ""
    observation_1: str = ""
    observation_2: str = ""
    notes: str = ""
    manager_verdict: str = ""
    manager_note: str = ""


@dataclass(frozen=True, slots=True)
class ExtractField:
    name: str
    observed: str
    visibility: Visibility
    confidence: int
    evidence: Evidence
    family: str = ""
    images: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ItemCounts:
    total_visible: int | None = None


@dataclass(frozen=True, slots=True)
class ExtractResult:
    fields: tuple[ExtractField, ...] = ()
    images_agree: bool = True
    item_counts: ItemCounts = field(default_factory=ItemCounts)
    product_type_scores: dict[str, int] = field(default_factory=dict)
