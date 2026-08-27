import csv
from pathlib import Path

import pytest

from core.exceptions.inbound_qc import InboundQcError
from pipelines.inbound_qc.category import CATEGORY_BEDSHEET, CATEGORY_GENERIC, detect_category
from pipelines.inbound_qc.columns import checklist_from_headers
from pipelines.inbound_qc.extract import extract_prompt, parse_extract_payload
from pipelines.inbound_qc.judge import (
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
)
from pipelines.inbound_qc.view import ReviewStore, finding_payload

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


def test_judge_prompt_asks_for_short_structured_analysis() -> None:
    prompt = judge_prompt([])
    assert "observation_1" in prompt
    assert "observation_2" in prompt
    assert "analysis — one short sentence" in prompt
    assert "Do not use OCR" in prompt
    assert "low (drop)" in prompt
    assert "between text and image" in prompt
    assert "A bedsheet set is the same product type" in prompt


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
    assert "bedsheet SKU" in prompt
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
