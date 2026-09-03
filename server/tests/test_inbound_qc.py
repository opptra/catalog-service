import csv
import zipfile
from pathlib import Path

import pytest

from core.clients.openrouter import OpenRouterClient
from core.exceptions.inbound_qc import InboundQcError
from core.exceptions.openrouter import OpenRouterError
from pipelines.inbound_qc.category import CATEGORY_BEDSHEET, CATEGORY_GENERIC, detect_category
from pipelines.inbound_qc.columns import checklist_from_headers
from pipelines.inbound_qc.extract import (
    _data_url,
    _for_vision,
    extract_prompt,
    parse_extract_payload,
)
from pipelines.inbound_qc.judge import (
    bedsheet_sizes_are_similar,
    build_judge_pairs,
    judge_prompt,
    parse_judge_payload,
    structural_findings,
)
from pipelines.inbound_qc.loaders import load_sku_bundles, read_sku_image
from pipelines.inbound_qc.report import write_reports, write_sources
from pipelines.inbound_qc.run import run_inbound_qc
from pipelines.inbound_qc.types import (
    ExtractField,
    ExtractResult,
    Finding,
    ImageRef,
    ItemCounts,
    SkuBundle,
    conflict_is_priority,
    pick_product_type,
)
from pipelines.inbound_qc.view import (
    IMAGE_LINKS_COLUMN,
    ISSUE_COLUMN,
    LISTED_COLUMN,
    PHOTOS_COLUMN,
    WHY_COLUMN,
    ReviewStore,
    build_attributes_with_findings_csv,
    finding_payload,
    format_finding_line,
)

_REPO = Path(__file__).resolve().parents[2]
_SAMPLE = _REPO / "sample_data" / "one"


def _cortina_bundle() -> SkuBundle:
    bundles = load_sku_bundles(
        _SAMPLE / "bedsheet_mandatoryV1.csv",
        _SAMPLE / "images.zip",
    )
    assert len(bundles) == 1
    return bundles[0]


def test_sample_zip_pairs_two_images() -> None:
    bundle = _cortina_bundle()
    assert bundle.sku_id == "COR-B0GQHP66NB"
    assert [image.filename for image in bundle.images] == ["image_01.jpg", "image_02.jpg"]
    assert all(image.content for image in bundle.images)


def _mini_catalog(tmp_path: Path) -> tuple[Path, Path]:
    product = tmp_path / "attributes.csv"
    product.write_text("SKU,Color\nA,Red\nB,Blue\nC,Green\n", encoding="utf-8")
    jpeg = b"\xff\xd8\xff" + b"\x00" * 32
    zip_path = tmp_path / "images.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for sku_id in ("A", "B", "C"):
            archive.writestr(f"images/{sku_id}/image_01.jpg", jpeg)
    return product, zip_path


def test_load_sku_bundles_limit_reads_first_n(tmp_path: Path) -> None:
    product, zip_path = _mini_catalog(tmp_path)
    bundles = load_sku_bundles(product, zip_path, limit=2)
    assert [bundle.sku_id for bundle in bundles] == ["A", "B"]
    assert all(bundle.images for bundle in bundles)


def test_load_sku_bundles_sku_ids_then_limit(tmp_path: Path) -> None:
    product, zip_path = _mini_catalog(tmp_path)
    bundles = load_sku_bundles(product, zip_path, sku_ids={"C", "B"}, limit=1)
    assert [bundle.sku_id for bundle in bundles] == ["B"]


def test_cli_limit_writes_one_sku(tmp_path: Path) -> None:
    from pipelines.inbound_qc.cli import main

    product, zip_path = _mini_catalog(tmp_path)
    rc = main(
        [
            "--product",
            str(product),
            "--images",
            str(zip_path),
            "--limit",
            "1",
            "--skip-vision",
            "--no-review",
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 0
    summary = (tmp_path / "out" / "latest" / "summary.csv").read_text(encoding="utf-8")
    assert "A," in summary
    assert "B," not in summary


def test_judge_pairs_include_intra_row_and_cross_modal() -> None:
    bundle = SkuBundle(
        sku_id="X",
        attributes={
            "SKU": "X",
            "Color": "White & Grey",
            "Pattern": "Floral",
            "Product Name / Title": "Navy sheet",
        },
        images=(),
    )
    extract = ExtractResult(
        fields=(
            ExtractField(
                name="color",
                observed="sage green floral on cream",
                visibility="clear",
                confidence=88,
                evidence="on_product",
                images=("image_01.jpg",),
            ),
            ExtractField(
                name="pattern",
                observed="floral",
                visibility="clear",
                confidence=90,
                evidence="on_product",
                images=("image_01.jpg",),
            ),
        )
    )
    checklist = checklist_from_headers(["SKU", "Color", "Pattern", "Product Name / Title"])
    pairs = {item.pair_id: item for item in build_judge_pairs(bundle, checklist, extract)}
    assert "ir:color" in pairs
    assert "cm:color" in pairs
    assert pairs["cm:color"].observed == "sage green floral on cream"
    assert pairs["cm:pattern"].catalog_value == "Floral"


def test_judge_uses_inferred_size_but_skips_not_visible() -> None:
    bundle = SkuBundle(
        sku_id="X",
        attributes={"SKU": "X", "Size": "Single", "Color": "White"},
    )
    extract = ExtractResult(
        fields=(
            ExtractField(
                name="size",
                observed="looks large",
                visibility="inferred",
                confidence=40,
                evidence="room_context",
            ),
            ExtractField(
                name="color",
                observed="",
                visibility="not_visible",
                confidence=10,
                evidence="none",
            ),
        )
    )
    checklist = checklist_from_headers(["SKU", "Size", "Color"])
    ids = {item.pair_id for item in build_judge_pairs(bundle, checklist, extract)}
    assert "cm:size" in ids
    assert "cm:color" not in ids


def test_judge_skips_tbd_and_ocr_extract() -> None:
    bundle = SkuBundle(
        sku_id="X",
        attributes={
            "SKU": "X",
            "Color": "TBD",
            "Size": "Single",
            "Product Description": "TBD",
        },
    )
    extract = ExtractResult(
        fields=(
            ExtractField(
                name="ocr",
                observed="8114 DUSTY YELLOW",
                visibility="clear",
                confidence=90,
                evidence="on_product",
            ),
            ExtractField(
                name="size",
                observed="single",
                visibility="clear",
                confidence=90,
                evidence="on_product",
            ),
        )
    )
    pairs = build_judge_pairs(
        bundle, checklist_from_headers(["SKU", "Color", "Size", "Product Description"]), extract
    )
    ids = {item.pair_id for item in pairs}
    assert "ir:color" not in ids
    assert "cm:color" not in ids
    assert "cm:ocr" not in ids
    assert "cm:size" in ids


def test_parse_judge_drops_low_severity() -> None:
    bundle = SkuBundle(
        sku_id="X",
        attributes={"SKU": "X", "Color": "Yellow", "Product Description": "dusty yellow"},
    )
    pairs = build_judge_pairs(
        bundle, checklist_from_headers(["SKU", "Color", "Product Description"]), extract=None
    )
    findings = parse_judge_payload(
        {
            "conflicts": [
                {
                    "pair_id": "ir:color",
                    "severity": "low",
                    "observation_1": "Catalog Color: Yellow",
                    "observation_2": "Title: dusty yellow",
                    "analysis": "same family",
                    "certainty": 88,
                    "similarity": 82,
                }
            ]
        },
        pairs,
        "X",
    )
    assert findings == []


def test_judge_item_count_pair_uses_visible_total() -> None:
    bundle = SkuBundle(
        sku_id="X",
        attributes={"SKU": "X", "Number of Items": "3"},
    )
    extract = ExtractResult(item_counts=ItemCounts(total_visible=2))
    pairs = build_judge_pairs(bundle, checklist_from_headers(["SKU", "Number of Items"]), extract)
    count = [item for item in pairs if item.pair_id == "cm:item_count"]
    assert count and count[0].observed == "2"
    assert count[0].field == "Number of Items"


def test_bedsheet_judge_skips_item_count() -> None:
    bundle = SkuBundle(
        sku_id="X",
        attributes={
            "SKU": "X",
            "Product Type": "Bedsheet Set",
            "Number of Items": "3",
            "Bed Size": "Double",
        },
    )
    extract = ExtractResult(item_counts=ItemCounts(total_visible=1))
    headers = ["SKU", "Product Type", "Number of Items", "Bed Size"]
    checklist = checklist_from_headers(headers, attributes=bundle.attributes)
    assert checklist.category == CATEGORY_BEDSHEET
    assert "item_count" in checklist.visual
    pairs = build_judge_pairs(bundle, checklist, extract)
    assert all(item.pair_id != "cm:item_count" for item in pairs)


def test_parse_judge_payload_keeps_only_known_conflicts() -> None:
    bundle = SkuBundle(
        sku_id="X",
        attributes={"SKU": "X", "Color": "Navy", "Product Description": "crimson floral"},
    )
    pairs = build_judge_pairs(
        bundle, checklist_from_headers(["SKU", "Color", "Product Description"]), extract=None
    )
    findings = parse_judge_payload(
        {
            "conflicts": [
                {
                    "pair_id": "ir:color",
                    "severity": "high",
                    "observation_1": "Catalog Color: Navy",
                    "observation_2": "Title: crimson floral",
                    "analysis": "Navy vs crimson",
                    "certainty": 95,
                    "similarity": 15,
                },
                {
                    "pair_id": "nope",
                    "severity": "high",
                    "observation_1": "ignored",
                    "observation_2": "ignored",
                    "analysis": "ignored",
                    "certainty": 90,
                    "similarity": 10,
                },
            ]
        },
        pairs,
        "X",
    )
    assert len(findings) == 1
    assert findings[0].kind == "intra_row"
    assert findings[0].field == "Color"
    assert findings[0].observation_1 == "Catalog Color: Navy"
    assert "crimson" in findings[0].notes
    assert findings[0].confidence == 95
    assert findings[0].similarity == 15
    assert conflict_is_priority(findings[0].confidence, findings[0].similarity)


def test_conflict_priority_is_certainty_not_similarity() -> None:
    assert conflict_is_priority(95, 12) is True
    assert conflict_is_priority(90, 80) is False
    assert conflict_is_priority(70, 10) is False
    assert conflict_is_priority(None, 0) is False
    assert conflict_is_priority(90, None) is True


def test_bedsheet_treats_double_queen_king_as_similar() -> None:
    assert bedsheet_sizes_are_similar("Double", "King") is True
    assert bedsheet_sizes_are_similar("Queen", "double bed") is True
    assert bedsheet_sizes_are_similar("Single", "King") is False
    bundle = SkuBundle(sku_id="X", attributes={"SKU": "X", "Size": "Double", "Bed Size": "Double"})
    extract = ExtractResult(
        fields=(
            ExtractField(
                name="size",
                observed="king",
                visibility="inferred",
                confidence=70,
                evidence="room_context",
            ),
        )
    )
    checklist = checklist_from_headers(
        ["SKU", "Size", "Bed Size"], attributes={"Size": "Double", "Bed Size": "Double"}
    )
    assert checklist.category == CATEGORY_BEDSHEET
    ids = {item.pair_id for item in build_judge_pairs(bundle, checklist, extract)}
    assert "cm:size" not in ids
    single = SkuBundle(sku_id="X", attributes={"SKU": "X", "Size": "Single", "Bed Size": "Single"})
    ids_single = {
        item.pair_id
        for item in build_judge_pairs(
            single,
            checklist_from_headers(
                ["SKU", "Size", "Bed Size"], attributes={"Size": "Single", "Bed Size": "Single"}
            ),
            extract,
        )
    }
    assert "cm:size" in ids_single


def test_bedsheet_judge_keeps_only_priority_findings() -> None:
    bundle = SkuBundle(
        sku_id="X",
        attributes={"SKU": "X", "Color": "Yellow", "Product Description": "dusty yellow sheet"},
    )
    pairs = build_judge_pairs(
        bundle, checklist_from_headers(["SKU", "Color", "Product Description"]), extract=None
    )
    payload = {
        "conflicts": [
            {
                "pair_id": "ir:color",
                "severity": "medium",
                "observation_1": "Catalog Color: Yellow",
                "observation_2": "Title: dusty yellow",
                "analysis": "same family",
                "certainty": 88,
                "similarity": 82,
            }
        ]
    }
    generic = parse_judge_payload(payload, pairs, "X")
    assert len(generic) == 1
    bedsheet = parse_judge_payload(payload, pairs, "X", category=CATEGORY_BEDSHEET)
    assert bedsheet == []


def test_judge_prompt_asks_for_short_structured_analysis() -> None:
    prompt = judge_prompt([])
    assert "observation_1" in prompt
    assert "observation_2" in prompt
    assert "analysis — one short sentence" in prompt
    assert "Do not use OCR" in prompt
    assert "low (drop)" in prompt
    assert "between text and image" in prompt
    assert "Double, Queen, and King" not in prompt
    bedsheet = judge_prompt([], category=CATEGORY_BEDSHEET)
    assert "Double, Queen, and King are the same size family" in bedsheet
    assert "Catalog bedsheet vs photo duvet" in bedsheet
    assert "Omit product_type only when both sides are bedsheet" in bedsheet
    assert "Return only priority conflicts for colour and size" in bedsheet


def test_finding_payload_flags_certain_mismatch_not_near_match() -> None:
    mismatch = finding_payload(
        {
            "sku_id": "A",
            "severity": "warning",
            "kind": "cross_modal",
            "field": "Color",
            "catalog_value": "White",
            "observed": "Green",
            "confidence": "95",
            "similarity": "10",
            "notes": "white vs green",
            "image_files": "",
        }
    )
    near = finding_payload(
        {
            "sku_id": "A",
            "severity": "warning",
            "kind": "cross_modal",
            "field": "Color",
            "catalog_value": "Yellow",
            "observed": "dusty yellow",
            "confidence": "88",
            "similarity": "82",
            "notes": "shade of yellow",
            "image_files": "",
        }
    )
    assert mismatch["priority"] is True
    assert mismatch["confidence"] == 95
    assert near["priority"] is False
    assert near["similarity"] == 82


def test_review_store_sorts_priority_ahead_of_near_match(tmp_path: Path) -> None:
    report = tmp_path / "report"
    findings = [
        Finding(
            sku_id="NEAR",
            severity="warning",
            kind="cross_modal",
            field="Color",
            catalog_value="Yellow",
            observed="dusty yellow",
            confidence=88,
            similarity=82,
            notes="near-match shade",
        ),
        Finding(
            sku_id="HARD",
            severity="warning",
            kind="cross_modal",
            field="Color",
            catalog_value="White",
            observed="Green",
            confidence=95,
            similarity=10,
            notes="white vs green",
        ),
    ]
    write_reports(findings, sku_ids=["NEAR", "HARD"], directory=report)
    product = tmp_path / "attributes.csv"
    product.write_text("SKU\nNEAR\nHARD\n", encoding="utf-8")
    store = ReviewStore.open(
        report,
        product=product,
        images=_SAMPLE / "images.zip",
    )
    batch = store.batch_payload()
    assert batch["skus_with_priority"] == 1
    assert [item["sku_id"] for item in batch["skus"][:2]] == ["HARD", "NEAR"]
    hard = store.sku_payload("HARD")
    near = store.sku_payload("NEAR")
    assert hard["priority_count"] == 1
    assert hard["findings"][0]["priority"] is True
    assert near["priority_count"] == 0
    assert near["findings"][0]["priority"] is False
    hard_row = next(item for item in batch["skus"] if item["sku_id"] == "HARD")
    assert hard_row["findings_preview"][0]["field"] == "Color"
    store.close()


def test_structural_mixed_variants() -> None:
    bundle = SkuBundle(
        sku_id="X",
        attributes={"SKU": "X"},
        images=(
            ImageRef(filename="a.jpg", content=b"a"),
            ImageRef(filename="b.jpg", content=b"b"),
        ),
    )
    findings = structural_findings(bundle, ExtractResult(images_agree=False))
    assert findings[0].kind == "intra_folder"
    assert findings[0].confidence == 100
    assert findings[0].similarity == 0
    assert conflict_is_priority(findings[0].confidence, findings[0].similarity)
    assert structural_findings(bundle, ExtractResult(images_agree=True)) == []


def test_duvet_extract_raises_product_type_finding() -> None:
    bundle = SkuBundle(
        sku_id="D1",
        attributes={"SKU": "D1", "Product Type": "Bedsheet Set", "Bed Size": "Double"},
        images=(ImageRef(filename="image_01.jpg", content=b"x"),),
    )
    extract = ExtractResult(
        fields=(
            ExtractField(
                name="product_type",
                observed="duvet with visible loft",
                visibility="clear",
                confidence=88,
                evidence="on_product",
                images=("image_01.jpg",),
            ),
        )
    )
    findings = structural_findings(bundle, extract)
    assert len(findings) == 1
    assert findings[0].kind == "cross_modal"
    assert findings[0].field == "Product Type"
    assert "duvet" in findings[0].observed.lower()
    assert conflict_is_priority(findings[0].confidence, findings[0].similarity)
    checklist = checklist_from_headers(
        ["SKU", "Product Type", "Bed Size"], attributes=bundle.attributes
    )
    ids = {item.pair_id for item in build_judge_pairs(bundle, checklist, extract)}
    assert "cm:product_type" not in ids


def test_product_type_scores_pick_highest_and_flag() -> None:
    assert pick_product_type(
        {
            "bedsheet": 30,
            "duvet": 80,
            "comforter": 40,
            "quilt": 10,
            "blanket": 5,
            "duvet_cover": 15,
        }
    ) == ("duvet", 80)
    assert pick_product_type(
        {
            "bedsheet": 70,
            "duvet": 70,
            "comforter": 0,
            "quilt": 0,
            "blanket": 0,
            "duvet_cover": 0,
        }
    ) == ("bedsheet", 70)

    result = parse_extract_payload(
        {
            "fields": [
                {
                    "name": "product_type",
                    "observed": "bedsheet",
                    "visibility": "not_visible",
                    "confidence": 95,
                    "evidence": "on_product",
                    "images": ["image_01.jpg"],
                }
            ],
            "images_agree": True,
            "product_type_scores": {
                "bedsheet": 30,
                "duvet": 80,
                "comforter": 40,
                "quilt": 10,
                "blanket": 5,
                "duvet_cover": 15,
            },
        }
    )
    assert result.fields[0].observed == "duvet"
    assert result.fields[0].confidence == 80
    assert result.fields[0].visibility == "clear"
    bundle = SkuBundle(
        sku_id="D1",
        attributes={"SKU": "D1", "Product Type": "Bedsheet Set", "Bed Size": "Double"},
        images=(ImageRef(filename="image_01.jpg", content=b"x"),),
    )
    findings = structural_findings(bundle, result)
    assert len(findings) == 1
    assert findings[0].observed == "duvet"
    assert findings[0].confidence == 80
    assert "duvet 80" in findings[0].notes
    assert "bedsheet 30" in findings[0].notes
    assert conflict_is_priority(findings[0].confidence, findings[0].similarity)


def test_bedsheet_extract_does_not_flag_product_type() -> None:
    bundle = SkuBundle(
        sku_id="S1",
        attributes={"SKU": "S1", "Product Type": "Bedsheet Set", "Bed Size": "Double"},
        images=(ImageRef(filename="image_01.jpg", content=b"x"),),
    )
    extract = ExtractResult(
        fields=(
            ExtractField(
                name="product_type",
                observed="flat bedsheet set",
                visibility="clear",
                confidence=90,
                evidence="on_product",
            ),
        )
    )
    assert structural_findings(bundle, extract) == []


def test_parse_extract_payload_round_trip() -> None:
    result = parse_extract_payload(
        {
            "fields": [
                {
                    "name": "color",
                    "observed": "green",
                    "family": "green",
                    "visibility": "clear",
                    "confidence": 80,
                    "evidence": "on_product",
                    "images": ["a.jpg"],
                }
            ],
            "images_agree": True,
            "item_counts": {"total_visible": 3},
        }
    )
    assert result.fields[0].family == "green"
    assert result.item_counts.total_visible == 3
    leftover = parse_extract_payload(
        {
            "fields": [
                {
                    "name": "ocr",
                    "observed": "8114",
                    "visibility": "clear",
                    "confidence": 90,
                    "evidence": "on_product",
                    "images": [],
                }
            ],
            "ocr_text": ["King"],
            "images_agree": True,
        }
    )
    assert leftover.fields == ()
    aliased = parse_extract_payload(
        {
            "fields": [
                {
                    "name": "bed_size",
                    "observed": "king",
                    "family": "king",
                    "visibility": "clear",
                    "confidence": 80,
                    "evidence": "on_product",
                    "images": [],
                }
            ],
            "images_agree": True,
        }
    )
    assert aliased.fields[0].name == "size"


def test_vision_encodes_tiff_as_jpeg() -> None:
    from io import BytesIO

    from PIL import Image as PilImage

    buffer = BytesIO()
    PilImage.new("RGB", (48, 32), color=(12, 34, 56)).save(buffer, format="TIFF")
    jpeg, content_type = _for_vision(buffer.getvalue(), "image/tiff")
    assert content_type == "image/jpeg"
    assert jpeg[:3] == b"\xff\xd8\xff"
    url = _data_url(
        ImageRef(filename="sheet.tif", content=buffer.getvalue(), content_type="image/tiff")
    )
    assert url is not None
    assert url.startswith("data:image/jpeg;base64,")


def test_tool_arguments_surfaces_provider_error() -> None:
    with pytest.raises(OpenRouterError, match="Provider returned error"):
        OpenRouterClient._tool_arguments(
            {"error": {"message": "Provider returned error"}},
            tool_name="extract_sku",
        )


def test_checklist_and_tool_are_header_driven_not_category() -> None:
    from pipelines.inbound_qc.tools import extract_tool

    toaster = checklist_from_headers(["SKU", "Color", "Material"])
    assert toaster.visual == ("color", "material")
    assert "size" not in toaster.visual
    assert "bed_size" not in toaster.visual
    params = extract_tool(toaster)["function"]["parameters"]["properties"]
    enum = params["fields"]["items"]["properties"]["name"]["enum"]
    assert enum == ["color", "material"]
    assert "item_counts" not in params

    sized = checklist_from_headers(["SKU", "Size", "Color"])
    assert "size" in sized.visual
    assert "bed_size" not in sized.visual
    assert sized.category == CATEGORY_GENERIC


def test_bedsheet_category_adds_product_type_to_checklist() -> None:
    headers = ["SKU", "Color", "Bed Size", "Product Type"]
    row = {"SKU": "X", "Color": "Yellow", "Bed Size": "Single", "Product Type": "Bedsheet"}
    checklist = checklist_from_headers(headers, attributes=row)
    assert checklist.category == CATEGORY_BEDSHEET
    assert checklist.visual[0] == "product_type"
    from pipelines.inbound_qc.tools import extract_tool

    params = extract_tool(checklist)["function"]["parameters"]
    assert "product_type_scores" in params["properties"]
    assert "product_type_scores" in params["required"]
    assert (
        detect_category(["SKU", "Color", "Product Type"], {"Product Type": "Bedsheet"})
        == CATEGORY_BEDSHEET
    )
    assert detect_category(["SKU", "Color"], {"Color": "Black"}) == CATEGORY_GENERIC


def test_run_inbound_qc_without_client_has_no_findings() -> None:
    findings = run_inbound_qc(_cortina_bundle(), checklist_from_headers([]), client=None)
    assert findings == []


def test_run_inbound_qc_extract_then_judge() -> None:
    class FakeClient:
        def call_tool(self, prompt: str, *, tool: dict, **kwargs: object) -> dict:
            name = tool["function"]["name"]
            if str(name).endswith("extract"):
                return {
                    "fields": [
                        {
                            "name": "color",
                            "observed": "sage green",
                            "visibility": "clear",
                            "confidence": 90,
                            "evidence": "on_product",
                            "images": ["image_01.jpg"],
                        }
                    ],
                    "images_agree": True,
                }
            return {
                "conflicts": [
                    {
                        "pair_id": "cm:color",
                        "severity": "high",
                        "observation_1": "Catalog Color: White & Grey",
                        "observation_2": "Photo: sage green",
                        "analysis": "grey vs green",
                        "certainty": 92,
                        "similarity": 12,
                    }
                ]
            }

    bundle = _cortina_bundle()
    checklist = checklist_from_headers(list(bundle.attributes))
    findings = run_inbound_qc(bundle, checklist, client=FakeClient(), model="test")
    color = [item for item in findings if item.kind == "cross_modal" and item.field == "Color"]
    assert color
    assert "green" in color[0].notes
    assert color[0].confidence == 92
    assert color[0].similarity == 12
    assert color[0].confidence != 90


def test_write_reports(tmp_path: Path) -> None:
    findings = [
        Finding(
            sku_id="A",
            severity="warning",
            kind="intra_row",
            field="Color",
            catalog_value="Grey",
            observed="green",
        )
    ]
    findings_path, summary_path = write_reports(findings, sku_ids=["A", "B"], directory=tmp_path)
    text = findings_path.read_text(encoding="utf-8")
    assert "manager_verdict" in text
    assert "similarity" in text
    assert "observation_1" in text
    assert "A" in text
    summary = summary_path.read_text(encoding="utf-8")
    assert "B" in summary
    assert "0" in summary


def test_write_sources_records_absolute_paths(tmp_path: Path) -> None:
    product = tmp_path / "attributes.csv"
    images = tmp_path / "images.zip"
    product.write_text("SKU\nX\n", encoding="utf-8")
    images.write_bytes(b"PK")
    path = write_sources(tmp_path / "report", product=product, images=images)
    text = path.read_text(encoding="utf-8")
    assert str(product.resolve()) in text
    assert str(images.resolve()) in text


def test_format_finding_line_and_attributes_export(tmp_path: Path) -> None:
    line = format_finding_line(
        {
            "field": "Color",
            "catalog_value": "RED",
            "observed": "gray",
            "notes": "different",
            "confidence": 99,
            "priority": True,
        }
    )
    assert "Color [priority]" in line
    assert "RED → gray" in line
    assert "99% certain" in line
    product = tmp_path / "attributes.csv"
    product.write_text("SKU,Color\nA,Red\nB,Blue\n", encoding="utf-8")
    findings = [
        {
            "sku_id": "A",
            "severity": "warning",
            "kind": "cross_modal",
            "field": "Color",
            "catalog_value": "Red",
            "observed": "Blue",
            "visibility": "",
            "confidence": "95",
            "similarity": "10",
            "image_files": "",
            "observation_1": "",
            "observation_2": "",
            "notes": "mismatch",
            "manager_verdict": "",
            "manager_note": "",
        }
    ]
    text = build_attributes_with_findings_csv(product, findings).decode("utf-8")
    reader = csv.DictReader(text.splitlines())
    assert ISSUE_COLUMN in (reader.fieldnames or [])
    assert IMAGE_LINKS_COLUMN in (reader.fieldnames or [])
    rows = list(reader)
    assert [row["SKU"] for row in rows] == ["A"]
    assert rows[0]["Color"] == "Red"
    assert rows[0][ISSUE_COLUMN] == "Color"
    assert rows[0][LISTED_COLUMN] == "Red"
    assert rows[0][PHOTOS_COLUMN] == "Blue"
    assert rows[0][WHY_COLUMN] == "mismatch"
    assert rows[0][IMAGE_LINKS_COLUMN] == ""


def test_export_csv_adds_image_links_from_sidecar(tmp_path: Path) -> None:
    product = tmp_path / "attributes.csv"
    product.write_text("SKU,Color\nA,Red\nB,Blue\n", encoding="utf-8")
    (tmp_path / "image_links.csv").write_text(
        "SKU,Image links\n"
        "A,https://drive.google.com/file/d/one/view; https://drive.google.com/file/d/two/view\n"
        "B,https://drive.google.com/file/d/bee/view\n",
        encoding="utf-8",
    )
    findings = [
        {
            "sku_id": "A",
            "severity": "warning",
            "kind": "cross_modal",
            "field": "Color",
            "catalog_value": "Red",
            "observed": "Blue",
            "visibility": "",
            "confidence": "95",
            "similarity": "10",
            "image_files": "image_02.jpg",
            "observation_1": "",
            "observation_2": "",
            "notes": "mismatch",
            "manager_verdict": "",
            "manager_note": "",
        }
    ]
    text = build_attributes_with_findings_csv(product, findings).decode("utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    assert [row["SKU"] for row in rows] == ["A"]
    assert rows[0][IMAGE_LINKS_COLUMN] == "https://drive.google.com/file/d/two/view"


def test_export_keeps_only_priority_issues(tmp_path: Path) -> None:
    product = tmp_path / "attributes.csv"
    product.write_text("SKU,Color\nA,Red\nB,Blue\nC,Green\n", encoding="utf-8")
    findings = [
        {
            "sku_id": "A",
            "severity": "warning",
            "kind": "cross_modal",
            "field": "Color",
            "catalog_value": "catalog Color: RED",
            "observed": "image shows gray floral",
            "visibility": "",
            "confidence": "95",
            "similarity": "10",
            "image_files": "image_01.jpg",
            "observation_1": "",
            "observation_2": "",
            "notes": (
                "Photos look like a filled covering, not a bedsheet. Scores: duvet 90, bedsheet 20."
            ),
            "manager_verdict": "",
            "manager_note": "",
        },
        {
            "sku_id": "A",
            "severity": "warning",
            "kind": "cross_modal",
            "field": "Product Type",
            "catalog_value": "Bedsheet Set",
            "observed": "duvet cover",
            "visibility": "",
            "confidence": "92",
            "similarity": "10",
            "image_files": "image_01.jpg",
            "observation_1": "",
            "observation_2": "",
            "notes": "Photos look like a filled covering, not a bedsheet.",
            "manager_verdict": "",
            "manager_note": "",
        },
        {
            "sku_id": "B",
            "severity": "warning",
            "kind": "cross_modal",
            "field": "Color",
            "catalog_value": "Blue",
            "observed": "navy",
            "visibility": "",
            "confidence": "88",
            "similarity": "82",
            "image_files": "",
            "observation_1": "",
            "observation_2": "",
            "notes": "same family",
            "manager_verdict": "",
            "manager_note": "",
        },
    ]
    text = build_attributes_with_findings_csv(product, findings).decode("utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    assert [row["SKU"] for row in rows] == ["A", "A"]
    assert [row[ISSUE_COLUMN] for row in rows] == ["Color", "Product Type"]
    assert rows[0][LISTED_COLUMN] == "RED"
    assert rows[0][PHOTOS_COLUMN] == "image shows gray floral"
    assert rows[0][WHY_COLUMN] == "Photos look like a filled covering, not a bedsheet."
    assert "Scores" not in rows[0][WHY_COLUMN]
    assert rows[1][LISTED_COLUMN] == "Bedsheet Set"
    assert rows[1][PHOTOS_COLUMN] == "duvet cover"


def test_review_store_skips_ocr_findings_and_maps_images(tmp_path: Path) -> None:
    report = tmp_path / "report"
    findings = [
        Finding(
            sku_id="COR-B0GQHP66NB",
            severity="warning",
            kind="cross_modal",
            field="Color",
            catalog_value="White & Grey",
            observed="sage",
            image_files="image_01.jpg",
        ),
        Finding(
            sku_id="COR-B0GQHP66NB",
            severity="warning",
            kind="intra_row",
            field="Material",
            catalog_value="Microfiber",
            observed="Cloud Cotton",
        ),
    ]
    write_reports(findings, sku_ids=["COR-B0GQHP66NB"], directory=report)
    with (report / "findings.csv").open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sku_id",
                "severity",
                "kind",
                "field",
                "catalog_value",
                "observed",
                "visibility",
                "confidence",
                "similarity",
                "image_files",
                "observation_1",
                "observation_2",
                "notes",
                "manager_verdict",
                "manager_note",
            ],
        )
        writer.writerow(
            {
                "sku_id": "COR-B0GQHP66NB",
                "severity": "warning",
                "kind": "ocr",
                "field": "ocr",
                "catalog_value": "",
                "observed": "8114 DUSTY YELLOW",
                "visibility": "clear",
                "confidence": "",
                "similarity": "",
                "image_files": "image_01.jpg;image_02.jpg",
                "observation_1": "",
                "observation_2": "",
                "notes": "on-image text not found in any CSV value",
                "manager_verdict": "",
                "manager_note": "",
            }
        )
    store = ReviewStore.open(
        report,
        product=_SAMPLE / "bedsheet_mandatoryV1.csv",
        images=_SAMPLE / "images.zip",
    )
    batch = store.batch_payload()
    assert batch["finding_count"] == 2
    assert batch["skus"][0]["kinds"] == ["cross_modal", "intra_row"]
    detail = store.sku_payload("COR-B0GQHP66NB")
    assert [item["kind"] for item in detail["findings"]] == ["cross_modal", "intra_row"]
    assert detail["images"][0]["filename"] == "image_01.jpg"
    assert detail["images"][0]["flagged"] is True
    assert any(attr["name"] == "Color" for attr in detail["attributes"])
    photo = store.image("COR-B0GQHP66NB", "image_01.jpg")
    assert photo.content
    assert photo.content_type == "image/jpeg"
    store.close()


def test_review_store_serves_tiff_as_preview_jpeg(tmp_path: Path) -> None:
    from io import BytesIO

    from PIL import Image as PilImage

    product = tmp_path / "attributes.csv"
    product.write_text("SKU,Color\nTIFSKU,Red\n", encoding="utf-8")
    tiff = BytesIO()
    PilImage.new("RGB", (48, 32), color=(9, 8, 7)).save(tiff, format="TIFF")
    zip_path = tmp_path / "images.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("images/TIFSKU/image_01.tif", tiff.getvalue())
    report = tmp_path / "report"
    write_reports([], sku_ids=["TIFSKU"], directory=report)
    store = ReviewStore.open(report, product=product, images=zip_path)
    assert store.sku_payload("TIFSKU")["images"][0]["content_type"] == "image/jpeg"
    photo = store.image("TIFSKU", "image_01.tif")
    assert photo.content_type == "image/jpeg"
    assert photo.content
    assert photo.content[:3] == b"\xff\xd8\xff"
    assert store.image("TIFSKU", "image_01.tif").content is photo.content
    store.close()


def test_read_sku_image_rejects_path_traversal() -> None:
    zip_path = _SAMPLE / "images.zip"
    with pytest.raises(InboundQcError, match="invalid image filename"):
        read_sku_image(zip_path, "COR-B0GQHP66NB", "../image_01.jpg")
    with pytest.raises(InboundQcError, match="invalid image filename"):
        read_sku_image(zip_path, "COR-B0GQHP66NB", "..")


def test_extract_prompt_observes_photos_not_catalog() -> None:
    bundle = _cortina_bundle()
    prompt = extract_prompt(
        bundle, checklist_from_headers(list(bundle.attributes), attributes=bundle.attributes)
    )
    assert "Look only at the product photos" in prompt
    assert "lists this as a bedsheet" in prompt
    assert "product_type_scores" in prompt
    assert "independently" in prompt
    assert "visible loft" in prompt
    assert "duvet" in prompt
    assert "comforter" in prompt
    assert "pillow" not in prompt.lower()
    assert "infer Single/Double/Queen/King" in prompt
    assert "Do not OCR" in prompt
    assert "Do not assume catalog values" in prompt
    assert "Image 1 is image_01.jpg" in prompt
    assert "bed_size" not in prompt
    assert "styled room" not in prompt
    assert "GSM" not in prompt
    assert "White & Grey" not in prompt
    assert "Microfiber" not in prompt


def test_generic_extract_prompt_when_category_unknown() -> None:
    bundle = SkuBundle(
        sku_id="SHOE-1",
        attributes={"SKU": "SHOE-1", "Color": "Black", "Material": "Leather"},
        images=(ImageRef(filename="image_01.jpg", content=b"x"),),
    )
    checklist = checklist_from_headers(list(bundle.attributes), attributes=bundle.attributes)
    assert checklist.category == CATEGORY_GENERIC
    prompt = extract_prompt(bundle, checklist)
    assert "Do not assume the product category" in prompt
    assert "bedsheet SKU" not in prompt
    assert "Do not OCR" in prompt


def test_cli_no_review_writes_reports(tmp_path: Path) -> None:
    from pipelines.inbound_qc.cli import main

    rc = main(
        [
            "--product",
            str(_SAMPLE / "bedsheet_mandatoryV1.csv"),
            "--images",
            str(_SAMPLE / "images.zip"),
            "--skip-vision",
            "--no-review",
            "--out-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert (tmp_path / "latest" / "findings.csv").is_file()
    assert (tmp_path / "latest" / "sources.json").is_file()
    assert (tmp_path / "latest" / "attributes_with_priority_issues.csv").is_file()


def test_cli_launches_review_after_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from pipelines.inbound_qc import cli as qc_cli

    seen: dict[str, object] = {}

    def fake_serve(report: Path, **kwargs: object) -> int:
        seen["report"] = report
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(qc_cli, "serve_review", fake_serve)
    rc = qc_cli.main(
        [
            "--product",
            str(_SAMPLE / "bedsheet_mandatoryV1.csv"),
            "--images",
            str(_SAMPLE / "images.zip"),
            "--skip-vision",
            "--out-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert seen["report"] == tmp_path / "latest"
    assert seen["open_browser"] is True
