from pipelines.generation.gallery import (
    SECTION_FORBIDDEN,
    SECTION_IDENTITY,
    SECTION_JSON_DNA,
    SECTION_ORDER,
    SECTION_OVERLAY_FACTS,
    SECTION_PRIORITY,
    SECTION_SCENE,
    SECTION_SLOT,
    SECTION_SUBJECT,
    SECTION_TASK,
    AssignedFact,
    CardFact,
    ProductIdentity,
    _fact_claim_tags_prompt,
    _product_card_prompt,
    _slot_prompt,
)
from pipelines.generation.tools import gallery_fact_claim_tags_tool, gallery_product_card_tool


def _section_index(prompt: str, title: str) -> int:
    marker = f"\n{title}\n"
    idx = prompt.find(marker)
    if idx >= 0:
        return idx
    if prompt.startswith(f"{title}\n"):
        return 0
    raise AssertionError(f"missing section {title!r}")


def test_slot_prompt_sections_in_locked_order() -> None:
    prompt = _slot_prompt(
        slot={
            "role": "Styled room hero",
            "kind": "hero",
            "content": "Main shot.",
            "pattern": "Hang.",
        },
        assigned_facts=[],
        brand_look="",
        identity=ProductIdentity(drop="63 inches"),
    )
    indexes = [_section_index(prompt, title) for title in SECTION_ORDER]
    assert indexes == sorted(indexes)
    assert SECTION_TASK in prompt
    assert SECTION_PRIORITY in prompt
    assert SECTION_SUBJECT in prompt
    assert SECTION_SLOT in prompt
    assert SECTION_SCENE in prompt
    assert SECTION_IDENTITY in prompt
    assert SECTION_OVERLAY_FACTS in prompt
    assert SECTION_JSON_DNA in prompt
    assert SECTION_FORBIDDEN in prompt


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
        identity=ProductIdentity(),
    )
    overlay_at = _section_index(prompt, SECTION_OVERLAY_FACTS)
    forbidden_at = _section_index(prompt, SECTION_FORBIDDEN)
    overlay = prompt[overlay_at:forbidden_at]
    assert "On-image text budget: 2 item(s)" in overlay
    assert "Create exactly one overlay callout for each facts JSON object" in overlay
    assert "Do not paint two overlays that restate the same shopper fact" in overlay
    assert "Letters printed on the physical product are identity" in overlay
    assert 'Each object\'s "value" is the on-image callout.' in overlay
    assert '"field" names what the value is.' in overlay
    assert (
        "A shopper reading the overlay must clearly understand what this fact is about."
    ) in overlay
    assert (
        "You may use field and value in one overlay to make that context, not as "
        "two separate labels."
    ) in overlay
    assert "If field would only repeat the value, do not use it." in overlay
    assert "Do not paint claim" in overlay
    assert "do not add a converted equivalent" in overlay
    assert "If value is a bare number and field names a unit" in overlay
    assert "Do not add extra measurements that are not in this facts JSON" in overlay
    assert '"claim": "opacity"' in overlay
    assert '"field": "Opacity"' in overlay
    assert '"value": "Light-filtering (50-60%)"' in overlay
    assert '"value": "Breathable"' in overlay
    assert '"value": "breathable"' not in overlay
    assert "On-image text budget" not in prompt[forbidden_at:]
    assert "including letter case" not in prompt
    assert "Paint the value as written." not in prompt
    assert "title case" not in prompt
    assert "source_field" not in prompt
    assert "Product Description" not in prompt


def test_slot_prompt_identity_is_not_overlay_copy() -> None:
    prompt = _slot_prompt(
        slot={
            "role": "Styled room hero",
            "kind": "hero",
            "content": "Main discovery shot.",
            "pattern": "Window with this product installed.",
        },
        assigned_facts=[],
        brand_look="",
        identity=ProductIdentity(drop="63 inches"),
    )
    assert '"drop": "63 inches"' in prompt
    assert "Never typeset this object" in prompt
    assert "Do not paint unless the same value is also in OVERLAY FACTS" not in prompt
    assert (
        "must not change drop, opening, pack, colour, print, or mount, "
        "including opening height vs floor."
    ) in prompt
    assert "Scale that opening to the product and the source photos" in prompt
    assert "Do not stretch the opening to door or floor-to-ceiling height" in prompt
    assert "Scale the architectural opening to the product" in prompt
    assert "Geometry outranks SCENE and OVERLAY" in prompt
    assert "keep the opening height vs floor and ceiling" in prompt
    assert "leaving the reference room behind" not in prompt
    assert "This shot has no on-image facts" in prompt
    assert "Paint no product specs" in prompt
    identity = prompt[
        _section_index(prompt, SECTION_IDENTITY) : _section_index(prompt, SECTION_OVERLAY_FACTS)
    ]
    overlay = prompt[
        _section_index(prompt, SECTION_OVERLAY_FACTS) : _section_index(prompt, SECTION_JSON_DNA)
    ]
    assert '"drop": "63 inches"' in identity
    assert "On-image text budget" not in identity
    assert '"field": "Length"' not in identity
    assert "[]" in overlay


def test_slot_prompt_scene_and_forbidden_do_not_restate_overlay_budget() -> None:
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
    scene = prompt[_section_index(prompt, SECTION_SCENE) : _section_index(prompt, SECTION_IDENTITY)]
    forbidden = prompt[_section_index(prompt, SECTION_FORBIDDEN) :]
    overlay = prompt[
        _section_index(prompt, SECTION_OVERLAY_FACTS) : _section_index(prompt, SECTION_JSON_DNA)
    ]
    assert "not copy to typeset" in scene
    assert "never paint any word from Slot, SUBJECT, Content, Pattern, or JSON DNA" in scene
    assert "If Pattern asks for measurement marks" in scene
    assert "place the OVERLAY FACTS labels only" in scene
    assert "If Content or Pattern asks for steps, guidance, care, or a sequence" in scene
    assert "Do not invent extra instruction labels, icons, or claims" in scene
    assert "The only shopper-facing instruction text is OVERLAY FACTS" in scene
    assert "Do not add related instruction icons or extra care rows" in overlay
    assert "On-image text budget" in overlay
    assert "Do not draw dimension arrows" in overlay
    assert "Overlay values appear as labels" in overlay
    assert "On-image text budget" not in forbidden
    assert "Do not draw a logo" in forbidden
    assert "no dual-unit charts" in forbidden.lower()
    assert "Do not copy badges, size tags, or feature callouts" in forbidden
    assert "Do not paint SUBJECT." in forbidden
    assert "Do not enlarge the architectural opening to fit overlay callouts." in forbidden
    assert "leaving the reference room behind" not in prompt


def test_slot_prompt_overlay_keeps_identity_and_json_dna_homes() -> None:
    prompt = _slot_prompt(
        slot={
            "role": "size chart",
            "kind": "infographic",
            "content": "Size chart beside this product.",
            "pattern": "Catalog size layout.",
        },
        assigned_facts=[
            AssignedFact(claim="dimensions", field="Length", value="63 inches"),
        ],
        brand_look='{"fonts":{"headline":"Inter"},"colors":{"primary":"#111111"}}',
        identity=ProductIdentity(drop="63 inches"),
    )
    identity = prompt[
        _section_index(prompt, SECTION_IDENTITY) : _section_index(prompt, SECTION_OVERLAY_FACTS)
    ]
    overlay = prompt[
        _section_index(prompt, SECTION_OVERLAY_FACTS) : _section_index(prompt, SECTION_JSON_DNA)
    ]
    dna = prompt[
        _section_index(prompt, SECTION_JSON_DNA) : _section_index(prompt, SECTION_FORBIDDEN)
    ]
    forbidden = prompt[_section_index(prompt, SECTION_FORBIDDEN) :]
    assert '"drop": "63 inches"' in identity
    assert "Never typeset this object" in identity
    assert "Do not paint unless the same value is also in OVERLAY FACTS" not in identity
    assert "On-image text budget: 1 item(s)" in overlay
    assert '"value": "63 Inches"' in overlay
    assert "Do not recolor the product" in dna
    assert "Do not paint typeface names or hex codes" in dna
    assert "Do not recolor the product" not in forbidden
    assert "On-image text budget" not in forbidden


def test_slot_prompt_no_facts_branch() -> None:
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
    overlay = prompt[
        _section_index(prompt, SECTION_OVERLAY_FACTS) : _section_index(prompt, SECTION_JSON_DNA)
    ]
    assert "This shot has no on-image facts" in overlay
    assert "Paint no product specs" in overlay
    assert "Keep letters that are physically on the product" in overlay
    assert "Empty facts JSON means no overlay chrome" in overlay
    assert "Empty facts JSON means zero words" not in prompt
    assert "[]" in overlay
    identity = prompt[
        _section_index(prompt, SECTION_IDENTITY) : _section_index(prompt, SECTION_OVERLAY_FACTS)
    ]
    assert "{}" in identity
    assert "[]" not in identity


def test_slot_prompt_subject_orients_without_overlay_or_description() -> None:
    prompt = _slot_prompt(
        slot={
            "role": "measurement_guide",
            "kind": "infographic",
            "content": "Shows measurement guidance.",
            "pattern": "Sizing diagram.",
        },
        assigned_facts=[],
        brand_look="",
        identity=ProductIdentity(drop="152.4", opening="Window"),
        category="Curtains",
        name="White Floral Window Curtain",
    )
    subject = prompt[_section_index(prompt, SECTION_SUBJECT) : _section_index(prompt, SECTION_SLOT)]
    overlay = prompt[
        _section_index(prompt, SECTION_OVERLAY_FACTS) : _section_index(prompt, SECTION_JSON_DNA)
    ]
    identity = prompt[
        _section_index(prompt, SECTION_IDENTITY) : _section_index(prompt, SECTION_OVERLAY_FACTS)
    ]
    assert "Kind of product: the SUBJECT line (not overlay copy)." in prompt
    assert "Category: Curtains" in subject
    assert "Category path:" not in subject
    assert "Name: White Floral Window Curtain" in subject
    assert "Do not paint these words" in subject
    assert "Description" not in subject
    assert "Category: Curtains" not in overlay
    assert "White Floral Window Curtain" not in overlay
    assert '"opening": "Window"' in identity
    empty = _slot_prompt(
        slot={"role": "hero", "kind": "hero", "content": "Main.", "pattern": "Hang."},
        assigned_facts=[],
        brand_look="",
    )
    empty_subject = empty[
        _section_index(empty, SECTION_SUBJECT) : _section_index(empty, SECTION_SLOT)
    ]
    assert "(none)" in empty_subject
    assert "Category:" not in empty_subject
    assert "Name:" not in empty_subject
    assert "Do not paint these words" not in empty_subject


def test_slot_prompt_subject_uses_catalog_path_when_present() -> None:
    prompt = _slot_prompt(
        slot={
            "role": "hero",
            "kind": "hero",
            "content": "Main shot.",
            "pattern": "Hang.",
        },
        assigned_facts=[],
        brand_look="",
        category_path=("Home", "Curtains", "Window Panels"),
        category="Panels",
        name="White Floral Window Curtain",
    )
    subject = prompt[_section_index(prompt, SECTION_SUBJECT) : _section_index(prompt, SECTION_SLOT)]
    assert "Category path: Home > Curtains > Window Panels" in subject
    assert "Category: Panels" not in subject
    assert "Name: White Floral Window Curtain" in subject


def test_product_card_prompt_keeps_one_unit_system_and_unique_facts() -> None:
    prompt = _product_card_prompt(
        {"Size": "7 feet", "Width (cm)": "110", "Length (CM)": "210", "Pack Count": "2"},
    )
    assert "Do not convert units" in prompt
    assert '"7 feet" stays "7 feet"' in prompt
    assert "must share that unit system too" in prompt
    assert "omit Size rather than mixing systems" in prompt
    assert "Every value must be a verbatim substring" in prompt
    assert "one shopper fact may appear only once" in prompt
    assert "omit the restatement" in prompt
    assert "IDENTITY" in prompt
    assert "source_field" not in prompt
    assert "field must not be empty" in prompt
    assert "CLAIMS" not in prompt
    assert "Bind CLAIMS first" not in prompt
    assert "Do not attach CI claims" in prompt
    assert "geometry object, never overlay copy" in prompt
    assert "same snippet (same unit system) into both" in prompt
    assert "window vs door" in prompt
    assert "aperture this product is made for" in prompt
    assert "not a restyled room" in prompt


def test_fact_claim_tags_prompt_cannot_add_facts() -> None:
    prompt = _fact_claim_tags_prompt(
        [CardFact("f1", "", "2 Curtain Panels", "Items Included")],
        ["included components", "panel configuration"],
    )
    assert "Do not add, split, or clone facts" in prompt
    assert "Each fact_id at most once" in prompt
    assert '"fact_id": "f1"' in prompt
    assert "included components" in prompt


def test_product_card_tool_requires_identity_and_facts() -> None:
    schema = gallery_product_card_tool()
    assert schema["function"]["name"] == "submit_product_card"
    required = schema["function"]["parameters"]["required"]
    assert "identity" in required
    assert "facts" in required
    description = schema["function"]["description"]
    assert "one shopper fact may appear only once" in description.lower()
    assert "keep the structured field and omit the restatement" in description
    assert "Do not attach CI claims here" in description
    assert "Bind each CLAIMS string by meaning" not in description
    identity_schema = schema["function"]["parameters"]["properties"]["identity"]
    assert identity_schema["type"] == "object"
    assert set(identity_schema["properties"]) == {
        "drop",
        "opening",
        "pack",
        "colour",
        "print",
        "mount",
    }
    fact_props = schema["function"]["parameters"]["properties"]["facts"]["items"]["properties"]
    assert set(fact_props) == {"field", "value"}


def test_fact_claim_tags_tool_cannot_add_facts() -> None:
    schema = gallery_fact_claim_tags_tool()
    assert schema["function"]["name"] == "submit_fact_claim_tags"
    params = schema["function"]["parameters"]
    assert params["required"] == ["tags"]
    tag_props = params["properties"]["tags"]["items"]["properties"]
    assert set(tag_props) == {"fact_id", "claim"}
    assert "Do not add, split, or clone facts" in schema["function"]["description"]
