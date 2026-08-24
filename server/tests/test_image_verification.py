from typing import Any, cast

from core.clients.openrouter import OpenRouterClient
from pipelines.generation import verify
from pipelines.generation.tools import IMAGE_VERIFICATION_TOOL_NAME


def test_below_threshold_uses_min_of_hard_axes() -> None:
    low_claims = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="m",
        attempt=1,
        identity=90,
        claims=79,
        quality=20,
    )
    low_identity = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="m",
        attempt=1,
        identity=50,
        claims=95,
        quality=20,
    )
    edge = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="m",
        attempt=1,
        identity=80,
        claims=80,
        quality=10,
    )
    quality_only = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="m",
        attempt=1,
        identity=90,
        claims=90,
        quality=10,
    )
    error = verify.error_result(model="m", attempt=1, error="verify_tool_call_failed")
    assert low_claims.below_threshold()
    assert low_identity.below_threshold()
    assert not edge.below_threshold()
    assert not quality_only.below_threshold()
    assert not error.below_threshold()
    assert quality_only.ship_score() == 90


def test_should_retry_honors_disable_flag(monkeypatch: Any) -> None:
    low = verify.VerificationResult(
        status=verify.STATUS_OK, model="m", attempt=1, identity=40, claims=90
    )
    monkeypatch.setattr(verify, "VERIFY_RETRY_ENABLED", True)
    assert verify.should_retry(low)
    monkeypatch.setattr(verify, "VERIFY_RETRY_ENABLED", False)
    assert not verify.should_retry(low)


def test_ok_json_is_the_persisted_snapshot() -> None:
    result = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="openai/gpt-4o",
        attempt=2,
        identity=88,
        claims=61,
        quality=70,
        reasoning="Badge reads Queen.",
        observed_text=("Queen", "210"),
        mismatches=(
            verify.VerificationMismatch(
                kind=verify.KIND_CONTRADICTION,
                source_field="Size",
                catalog="King",
                observed="Queen",
            ),
        ),
        attribute_name="IMAGE",
        role="hero",
        kind="packshot",
    )
    payload = result.to_json()
    assert payload["v"] == 2
    assert payload["confidence"] == 61
    assert payload["axes"] == {"identity": 88, "claims": 61, "quality": 70}
    assert payload["slot"] == {"name": "IMAGE", "role": "hero", "kind": "packshot"}
    assert payload["mismatches"][0]["kind"] == "contradiction"
    assert "expected" not in payload
    assert "visual_match" not in payload


def test_error_json_omits_score() -> None:
    payload = verify.error_result(model="openai/gpt-4o", attempt=1, error="boom").to_json()
    assert payload["status"] == "error"
    assert payload["error"] == "boom"
    assert "confidence" not in payload
    assert "mismatches" not in payload
    assert "axes" not in payload


def test_persist_payload_nests_previous_once() -> None:
    first = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="m",
        attempt=1,
        identity=40,
        claims=40,
        reasoning="Wrong size.",
        mismatches=(
            verify.VerificationMismatch(
                kind=verify.KIND_CONTRADICTION,
                source_field="Size",
                catalog="King",
                observed="Queen",
            ),
        ),
    )
    second = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="m",
        attempt=2,
        identity=91,
        claims=91,
        reasoning="Size now King.",
    )
    payload = verify.persist_payload(second, previous=first)
    assert payload["attempt"] == 2
    assert payload["confidence"] == 91
    assert payload["previous"]["attempt"] == 1
    assert payload["previous"]["confidence"] == 40
    assert "previous" not in payload["previous"]


def test_persist_payload_omits_previous_when_absent() -> None:
    result = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="m",
        attempt=1,
        identity=90,
        claims=90,
        reasoning="Clean.",
    )
    payload = verify.persist_payload(result)
    assert "previous" not in payload


def test_retry_addendum_lists_hard_axes_not_quality() -> None:
    result = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="m",
        attempt=1,
        identity=40,
        claims=40,
        quality=20,
        reasoning="Wrong size and color.",
        mismatches=(
            verify.VerificationMismatch(
                kind=verify.KIND_CONTRADICTION,
                source_field="Size",
                catalog="King",
                observed="Queen",
            ),
            verify.VerificationMismatch(
                kind=verify.KIND_IDENTITY,
                source_field="Color",
                catalog="White",
                observed="sage green",
            ),
            verify.VerificationMismatch(
                kind=verify.KIND_QUALITY,
                source_field=None,
                catalog=None,
                observed="product cropped at the hem",
            ),
            verify.VerificationMismatch(
                kind=verify.KIND_INVENTED,
                source_field=None,
                catalog=None,
                observed="FREE SHIPPING",
            ),
        ),
    )
    addendum = verify.retry_addendum(result)
    assert "Size" in addendum
    assert "King" in addendum
    assert "Queen" in addendum
    assert "White" in addendum
    assert "sage green" in addendum
    assert "FREE SHIPPING" in addendum
    assert "cropped" not in addendum
    assert "quality" not in addendum.lower()


def test_reference_image_urls_caps_at_three() -> None:
    urls = [f"https://example.com/{i}.jpg" for i in range(1, 6)]
    assert verify.reference_image_urls(urls) == urls[:3]
    assert verify.reference_image_urls([]) == []
    assert verify.reference_image_urls(None) == []


class _FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.image_urls: list[str] | None = None
        self.cache_prefix: str | None = None
        self.prompt: str | None = None
        self.tool_name: str | None = None

    def call_tool(
        self,
        prompt: str,
        *,
        model: str,
        tool: dict[str, Any],
        image_urls: list[str] | None = None,
        cache_prefix: str | None = None,
        max_tokens: int | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del model, session_id
        self.prompt = prompt
        self.image_urls = image_urls
        self.cache_prefix = cache_prefix
        self.tool_name = tool["function"]["name"]
        self.max_tokens = max_tokens
        return self.payload


def test_verify_image_attaches_generated_then_capped_sources(monkeypatch: Any) -> None:
    monkeypatch.setattr(verify.settings, "openrouter_verify_model", "openai/gpt-4o")
    client = _FakeClient(
        {
            "identity": 91,
            "claims": 88,
            "quality": 70,
            "reasoning": "Same white king set; little on-image text.",
            "observed_text": [],
            "mismatches": [],
        }
    )
    product = {
        "SKU": "ABC",
        "Size": "King",
        "Color": "White",
        "source_assets": ["https://example.com/source.jpg"],
    }
    generated = "https://signed.example/generated.png"
    sources = [f"https://signed.example/src{i}.png" for i in range(1, 6)]
    result = verify.verify_image(
        cast(OpenRouterClient, client),
        generated_image_url=generated,
        product=product,
        attempt=1,
        source_image_urls=sources,
        attribute_name="IMAGE",
        role="hero",
        kind="packshot",
    )
    assert client.image_urls == [generated, *sources[:3]]
    assert client.tool_name == IMAGE_VERIFICATION_TOOL_NAME
    assert client.cache_prefix is not None
    assert "source_assets" not in client.cache_prefix
    assert "https://example.com/source.jpg" not in client.cache_prefix
    assert "https://signed.example/src1.png" not in (client.cache_prefix or "")
    assert client.prompt is not None
    assert "attribute=IMAGE" in client.prompt
    assert "role=hero" in client.prompt
    assert "Amazon" not in client.prompt
    assert "If it appears in Description or any other value, it is NOT invented" in client.prompt
    assert "every key AND every value is a fact" in (client.cache_prefix or "")
    assert result.confidence == 88
    assert result.identity == 91
    assert result.claims == 88
    assert result.quality == 70
    assert not result.below_threshold()


def test_parse_computes_confidence_from_axes() -> None:
    parsed = verify._parse_tool(
        {
            "identity": 92,
            "claims": 61,
            "quality": 40,
            "reasoning": "Badge Queen.",
            "observed_text": ["Queen"],
            "mismatches": [
                {
                    "kind": "contradiction",
                    "source_field": "Size",
                    "catalog": "King",
                    "observed": "Queen",
                },
                {
                    "kind": "identity",
                    "source_field": "Color",
                    "catalog": "White",
                    "observed": "sage",
                },
                {
                    "kind": "quality",
                    "observed": "soft crop",
                },
            ],
        },
        model="m",
        attempt=1,
        attribute_name="A_PLUS",
    )
    assert parsed.ship_score() == 61
    assert parsed.below_threshold()
    kinds = {item.kind for item in parsed.mismatches}
    assert kinds == {"contradiction", "identity", "quality"}
    assert parsed.attribute_name == "A_PLUS"


def test_invented_mismatch_clears_catalog_fields() -> None:
    parsed = verify._parse_tool(
        {
            "identity": 90,
            "claims": 50,
            "quality": 80,
            "reasoning": "Invented slogan.",
            "observed_text": ["FREE SHIPPING"],
            "mismatches": [
                {
                    "kind": "invented",
                    "source_field": "Size",
                    "catalog": "King",
                    "observed": "FREE SHIPPING",
                }
            ],
        },
        model="m",
        attempt=1,
    )
    assert parsed.mismatches[0].kind == "invented"
    assert parsed.mismatches[0].source_field is None
    assert parsed.mismatches[0].catalog is None
    assert parsed.mismatches[0].observed == "FREE SHIPPING"


def test_verify_image_includes_description_in_product_data(monkeypatch: Any) -> None:
    monkeypatch.setattr(verify.settings, "openrouter_verify_model", "openai/gpt-4o")
    client = _FakeClient(
        {
            "identity": 95,
            "claims": 95,
            "quality": 80,
            "reasoning": "210 TC is in Description.",
            "observed_text": ["210 TC"],
            "mismatches": [],
        }
    )
    product = {
        "SKU": "ABC",
        "Size": "King",
        "Description": "Luxury 210 TC cotton sateen sheet set.",
    }
    result = verify.verify_image(
        cast(OpenRouterClient, client),
        generated_image_url="https://signed.example/generated.png",
        product=product,
        attempt=1,
    )
    assert "Luxury 210 TC cotton sateen sheet set." in (client.cache_prefix or "")
    assert "NOT invented" in (client.prompt or "")
    assert result.claims == 95
    assert result.mismatches == ()
