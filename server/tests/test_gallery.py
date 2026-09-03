import pytest

from core.exceptions import GalleryPlanError
from pipelines.generation.gallery import FactValue, _select_slots


def _slot(
    *,
    kind: str,
    role: str,
    order: int,
    feature_priority: list[str] | None = None,
    owns: str | None = None,
) -> dict:
    slot: dict = {
        "kind": kind,
        "role": role,
        "order": order,
        "priority": "core",
        "max_callouts": 0,
        "feature_priority": [],
    }
    if feature_priority is not None:
        slot["feature_priority"] = feature_priority
        slot["max_callouts"] = len(feature_priority)
    if owns is not None:
        slot["owns"] = owns
    return slot


def test_select_slots_fills_quantity_when_hero_roles_repeat() -> None:
    """CI often emits several hero variants with the same role and no owns key.

    Unique-role selection then yields 6 slots for a 7-image gallery; the leftover
    hero variant must fill the last slot instead of failing the job.
    """
    candidates = [
        _slot(kind="hero", role="kitchen lifestyle hero", order=1),
        _slot(kind="hero", role="kitchen lifestyle hero", order=2),
        _slot(kind="hero", role="kitchen lifestyle hero", order=3),
        _slot(
            kind="infographic",
            role="size chart",
            order=4,
            feature_priority=["dimensions"],
        ),
        _slot(
            kind="detail",
            role="construction diagram",
            order=5,
            feature_priority=["anti-slip"],
        ),
        _slot(
            kind="infographic",
            role="product features overview",
            order=6,
            feature_priority=["anti-slip"],
        ),
        _slot(
            kind="detail",
            role="anti-slip feature",
            order=7,
            feature_priority=["anti-slip"],
        ),
        _slot(
            kind="lifestyle",
            role="usage scenarios",
            order=8,
            feature_priority=["multi-purpose"],
        ),
    ]
    fact_board = {
        "dimensions": [FactValue("45x80 CM", "Size")],
        "anti-slip": [FactValue("rubber backing", "Material")],
        "multi-purpose": [FactValue("kitchen bathroom", "Usage")],
    }

    selected = _select_slots(candidates, quantity=7, fact_board=fact_board)

    assert [slot["role"] for slot in selected] == [
        "kitchen lifestyle hero",
        "size chart",
        "construction diagram",
        "product features overview",
        "anti-slip feature",
        "usage scenarios",
        "kitchen lifestyle hero",
    ]
    assert selected[0]["order"] == 1
    assert selected[6]["order"] == 2


def test_select_slots_prefers_fact_supported_before_filling_duplicates() -> None:
    candidates = [
        _slot(kind="hero", role="hero", order=1),
        _slot(kind="hero", role="hero", order=2),
        _slot(
            kind="infographic",
            role="size chart",
            order=3,
            feature_priority=["dimensions"],
        ),
        _slot(
            kind="detail",
            role="unsupported overlay",
            order=4,
            feature_priority=["missing claim"],
        ),
    ]
    fact_board = {"dimensions": [FactValue("120 cm", "Length")]}

    selected = _select_slots(candidates, quantity=3, fact_board=fact_board)

    assert [slot["role"] for slot in selected] == ["hero", "size chart", "unsupported overlay"]
    assert selected[0]["order"] == 1


def test_select_slots_raises_when_candidates_cannot_cover_quantity() -> None:
    candidates = [_slot(kind="hero", role="hero", order=1)]
    with pytest.raises(GalleryPlanError, match="1/3"):
        _select_slots(candidates, quantity=3, fact_board={})
