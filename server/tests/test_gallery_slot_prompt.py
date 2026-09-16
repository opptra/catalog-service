from pipelines.generation.gallery import AssignedFact, _fact_board_prompt, _slot_prompt
from pipelines.generation.tools import gallery_fact_board_tool


def test_slot_prompt_fact_rendering_contract() -> None:
    prompt = _slot_prompt(
        slot={
            "role": "Product features and benefits",
            "kind": "infographic",
            "content": (
                "Benefits infographic module: catalog-style callout layout beside this product."
            ),
            "pattern": "This product in frame; clean catalog composition.",
        },
        assigned_facts=[
            AssignedFact(
                claim="opacity",
                field="Opacity",
                value="Light-filtering (50-60%)",
            ),
            AssignedFact(
                claim="breathable / lightweight / all-season",
                field="breathable",
                value="breathable",
            ),
        ],
        brand_look="",
    )
    assert "On-image text budget: 2 item(s)" in prompt
    assert "Create exactly one overlay callout for each facts JSON object" in prompt
    assert "Letters printed on the physical product are identity" in prompt
    assert 'Each object\'s "value" is the on-image callout.' in prompt
    assert "including letter case" not in prompt
    assert "Paint the value as written." not in prompt
    assert "The first letter of the label is already uppercase." not in prompt
    assert "Do not paint all-capital letters." not in prompt
    assert "Do not capitalize every remaining word." not in prompt
    assert "Paint those JSON values now" not in prompt
    assert "Required overlay typesetting:" not in prompt
    assert "first letter of every word" not in prompt
    assert "immutable" not in prompt
    assert "source-of-truth" not in prompt
    assert "Never change" not in prompt
    assert "title case" not in prompt
    assert '"Breathable" paints as Breathable' not in prompt
    assert "hyphen" not in prompt.lower()
    assert '"field" names what the value is.' in prompt
    assert (
        "A shopper reading the overlay must clearly understand what this fact is about."
    ) in prompt
    assert (
        "You may use field and value in one overlay to make that context, not as "
        "two separate labels."
    ) in prompt
    assert "If field would only repeat the value, do not use it." in prompt
    assert "Sheet length" not in prompt
    assert "Paint field with the value" not in prompt
    assert "complete shopper phrase" not in prompt
    assert "width vs length" not in prompt
    assert "two numbers" not in prompt
    assert "Width 110 cm" not in prompt
    assert "field is reference for this brief, not overlay copy." not in prompt
    assert "Otherwise the value is enough" not in prompt
    assert "shopper heading" not in prompt
    assert "Do not paint claim" in prompt
    assert "do not add a converted equivalent" in prompt
    assert "If value is a bare number and field names a unit" in prompt
    assert "Do not add extra measurements that are not in this facts JSON" in prompt
    assert '"claim": "opacity"' in prompt
    assert '"field": "Opacity"' in prompt
    assert '"value": "Light-filtering (50-60%)"' in prompt
    assert '"value": "Breathable"' in prompt
    assert '"value": "breathable"' not in prompt
    assert "source_field" not in prompt
    assert "Product Description" not in prompt
    assert "once as overlay chrome" not in prompt
    assert "paint those digits/words exactly" not in prompt
    assert "Thread Count: 120" not in prompt
    assert "source_field + value" not in prompt
    assert "attribute name and unit context" not in prompt


def test_slot_prompt_closer_separates_content_from_facts() -> None:
    prompt = _slot_prompt(
        slot={
            "role": "Fabric texture close-up",
            "kind": "detail",
            "content": "Fabric texture module: tight macro of this listing's cloth.",
            "pattern": "Macro of the cloth.",
        },
        assigned_facts=[
            AssignedFact(
                claim="fabric name",
                field="Fabric",
                value="Microfiber",
            )
        ],
        brand_look="",
    )
    assert "Content and Pattern are the shot" in prompt
    assert "leaving the reference room behind" in prompt
    assert "not copy to typeset" in prompt
    assert "never paint any word from Slot, Content, Pattern, or JSON DNA" in prompt
    assert "Do not draw dimension arrows" in prompt
    assert "Overlay values appear as labels" in prompt
    assert "Numerals and units count as overlay chrome" in prompt
    assert "mute visual marks" not in prompt
    assert "Numerals and units on measurement lines count as" not in prompt
    assert "no dual-unit charts" in prompt
    assert "Do not copy badges, size tags, or feature callouts" in prompt
    assert "Only the facts JSON may determine overlay claims" in prompt
    assert "Overlay information may come only from the facts JSON" in prompt
    assert (
        "Visible overlay text comes from the value, using field in the same overlay "
        "when that makes the fact clear."
    ) in prompt
    assert "Do not paint field and value as two labels." in prompt
    assert "including letter case" not in prompt
    assert "Do not paint all-capital letters." not in prompt
    assert "Do not capitalize every remaining word." not in prompt
    assert "shopper-readable rendering" not in prompt
    assert "source_field + value" not in prompt
    assert "Overlay letters or digits may come only from the facts JSON" not in prompt
    assert "on-product print" in prompt
    assert "Empty facts JSON means no overlay chrome" in prompt
    assert "Do not invent unsupported specifications" in prompt
    assert "Keep the product's identity from the reference photos" in prompt
    assert "Content (composition only — not on-image copy):" in prompt
    assert "Content and Pattern describe infographic type" not in prompt
    assert (
        "Keep the product appearance from the reference photos as the visual priority" not in prompt
    )


def test_slot_prompt_no_facts_branch_unchanged() -> None:
    prompt = _slot_prompt(
        slot={
            "role": "Styled room hero",
            "kind": "hero",
            "content": "Main discovery shot. Product-first; no on-image specs.",
            "pattern": "Window with this product installed.",
        },
        assigned_facts=[],
        brand_look="",
    )
    assert "This shot has no on-image facts" in prompt
    assert "Paint no product specs" in prompt
    assert "Keep letters that are physically on the product" in prompt
    assert "Empty facts JSON means no overlay chrome" in prompt
    assert "Empty facts JSON means zero words" not in prompt
    assert "Content and Pattern are the shot" in prompt
    assert "Content (composition only — not on-image copy):" in prompt


def test_fact_board_prompt_keeps_one_unit_system_per_claim() -> None:
    prompt = _fact_board_prompt(
        {"Size": "7 feet", "Width (cm)": "110", "Length (CM)": "210"},
        ["product dimensions"],
    )
    assert "Do not convert units" in prompt
    assert '"7 feet" stays "7 feet"' in prompt
    assert "must share one unit system" in prompt
    assert "omit Size rather than mixing systems" in prompt
    assert "Every value must be a verbatim substring" in prompt
    assert "of PRODUCT DATA" in prompt
    assert "source_field" not in prompt
    assert "provenance only" not in prompt
    assert "generic copy container" in prompt
    assert "field must not be empty" in prompt
    assert "It is not overlay copy." in prompt


def test_fact_board_prompt_omits_restated_shopper_facts() -> None:
    prompt = _fact_board_prompt(
        {"Pack Count": "2", "Included Components": "2 Panels", "Colour": "Grey"},
        ["pack count", "included components", "colour"],
    )
    assert "one shopper fact may appear only once" in prompt
    assert "omit the other entirely" in prompt
    assert "Keep the more specific structured field" in prompt
    assert "Drop the restatement" in prompt
    assert "colour vs print" in prompt


def test_fact_board_tool_omits_restated_shopper_facts() -> None:
    description = gallery_fact_board_tool()["function"]["description"]
    assert "do not return two items that tell the shopper the same fact" in description
    assert "keep the structured field and omit the restatement" in description
