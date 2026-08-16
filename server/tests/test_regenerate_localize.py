from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from PIL import Image

from core.exceptions import AttributeValueRegenerationError
from entities.catalog.attribute_enums import AttributeDataType, AttributeName
from pipelines.generation import prompts, regenerate
from pipelines.generation.images import ImageGeneration
from pipelines.generation.localize import LOCALIZE_FAIL_MESSAGE, LocalizationImpossibleError
from services import job as job_service


def _png(color: tuple[int, int, int], size: tuple[int, int] = (16, 16)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeGcs:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.uploads: list[tuple[bytes, str, str]] = []

    def object_name_from_gs_uri(self, gs_uri: str) -> str | None:
        if not gs_uri.startswith("gs://bucket/"):
            return None
        return gs_uri.removeprefix("gs://bucket/")

    def download_bytes(self, object_name: str) -> bytes:
        return self.objects[object_name]

    def upload_bytes(self, data: bytes, object_name: str, content_type: str):
        self.uploads.append((data, object_name, content_type))
        return SimpleNamespace(gs_uri=f"gs://bucket/{object_name}")

    def signed_url_for_gs_uri(self, gs_uri: str, expiration_seconds: int = 0) -> str:
        return f"https://signed/{gs_uri}"


def test_localized_regenerate_bytes_returns_composite_not_candidate():
    source = _png((200, 40, 40))
    candidate_image = Image.new("RGB", (16, 16), (200, 50, 40))
    candidate_image.paste((20, 20, 180), (4, 4, 12, 12))
    candidate_buf = BytesIO()
    candidate_image.save(candidate_buf, format="PNG")
    candidate = candidate_buf.getvalue()

    gcs = _FakeGcs({"images/source.png": source})
    result = job_service._localized_regenerate_bytes(
        gcs, "gs://bucket/images/source.png", candidate
    )
    assert result != candidate
    with Image.open(BytesIO(result)) as out:
        assert out.getpixel((0, 0)) == (200, 40, 40)
        assert out.getpixel((6, 6)) == (20, 20, 180)


def test_localized_regenerate_bytes_raises_when_mask_covers_frame():
    gcs = _FakeGcs({"images/source.png": _png((30, 30, 30))})
    with pytest.raises(LocalizationImpossibleError):
        job_service._localized_regenerate_bytes(
            gcs, "gs://bucket/images/source.png", _png((200, 10, 10))
        )


def test_image_revise_prompt_includes_keep_frame_text_does_not():
    image_prompt = prompts.revise_generation_prompt(
        data_type=AttributeDataType.IMAGE,
        attribute_name=AttributeName.IMAGE,
        previous_prompt="previous image prompt",
        current_value="ignored",
        improvement="make the pillow navy",
    )
    text_prompt = prompts.revise_generation_prompt(
        data_type=AttributeDataType.TEXT,
        attribute_name=AttributeName.TITLE,
        previous_prompt="previous title prompt",
        current_value="Old title",
        improvement="shorter",
    )
    assert "change only the user-requested region" in image_prompt
    assert "change only the user-requested region" not in text_prompt


def test_regenerate_image_prompt_gets_keep_frame_not_via_shared_suffix(monkeypatch):
    captured: dict[str, str] = {}

    class _Client:
        def generate_gemini_image(self, prompt, **kwargs):
            captured["prompt"] = prompt
            return SimpleNamespace(content=_png((1, 2, 3)), content_type="image/png")

    monkeypatch.setattr(regenerate, "_references", lambda _ctx: [])
    ctx = SimpleNamespace()
    regenerate.regenerate_image(
        _Client(),
        ctx,
        image_prompt="paint the product",
        aspect_ratio="1:1",
        current_image_url="https://example/current.png",
    )
    assert "=== IMAGE EDIT KEEP FRAME ===" in captured["prompt"]
    assert "=== IMAGE EDIT KEEP FRAME ===" not in prompts.ensure_image_render_suffix(
        "paint the product"
    )


def test_regenerate_attribute_value_persists_composite_and_skips_on_fail(monkeypatch):
    source = _png((200, 40, 40))
    local_candidate = Image.new("RGB", (16, 16), (200, 50, 40))
    local_candidate.paste((20, 20, 180), (4, 4, 12, 12))
    candidate_buf = BytesIO()
    local_candidate.save(candidate_buf, format="PNG")
    local_bytes = candidate_buf.getvalue()
    global_bytes = _png((10, 200, 10))

    latest = SimpleNamespace(
        value="gs://bucket/images/source.png",
        prompt="stored prompt",
        attribute_id=1,
        sku_generation_job_id=2,
        marketplace_id=3,
        slot=0,
        version=1,
        external_id=uuid4(),
    )
    master = SimpleNamespace(
        id=1,
        name=AttributeName.IMAGE.value,
        data_type=AttributeDataType.IMAGE.value,
        external_id=uuid4(),
    )
    sku_job = SimpleNamespace(id=2, job_id=4, sku_id=5, external_id=uuid4())
    job = SimpleNamespace(
        job_type="GENERATION",
        marketplace_id=uuid4(),
        brand_id=uuid4(),
        external_id=uuid4(),
    )
    brand = SimpleNamespace(id=9)
    sku = SimpleNamespace(deleted_at=None)

    monkeypatch.setattr(
        job_service.attribute_value_repo, "get_latest_by_external_id", lambda *_a, **_k: latest
    )
    monkeypatch.setattr(job_service.attribute_master_repo, "get_by_id", lambda *_a, **_k: master)
    monkeypatch.setattr(job_service.sku_generation_job_repo, "get_by_id", lambda *_a, **_k: sku_job)
    monkeypatch.setattr(job_service.job_repo, "get_by_id", lambda *_a, **_k: job)
    monkeypatch.setattr(job_service.brand_repo, "get_by_external_id", lambda *_a, **_k: brand)
    monkeypatch.setattr(job_service.sku_master_repo, "get_by_id", lambda *_a, **_k: sku)
    monkeypatch.setattr(job_service.inputs, "load_context", lambda *_a, **_k: SimpleNamespace())
    monkeypatch.setattr(
        job_service.regenerate,
        "revise_prompt",
        lambda *_a, **_k: SimpleNamespace(prompt="revised prompt"),
    )
    monkeypatch.setattr(
        job_service.common_image, "parse_common_from_prompt", lambda *_a, **_k: None
    )
    monkeypatch.setattr(job_service.common_image, "extract", lambda *_a, **_k: "common")
    monkeypatch.setattr(job_service.common_image, "ensure_in_prompt", lambda prompt, _c: prompt)

    persist = MagicMock(return_value={"external_id": latest.external_id, "version": 2})
    monkeypatch.setattr(job_service, "_persist_attribute_value", persist)

    gcs = _FakeGcs({"images/source.png": source})
    client = MagicMock()

    def _regen(*_a, **_k):
        return ImageGeneration(content=local_bytes, content_type="image/jpeg", prompt="revised")

    monkeypatch.setattr(job_service.regenerate, "regenerate_image", _regen)
    result = job_service.regenerate_attribute_value(
        MagicMock(), client, gcs, value_external_id=latest.external_id, improvement="navy pillow"
    )
    assert persist.call_count == 1
    assert gcs.uploads[0][2] == "image/png"
    assert gcs.uploads[0][0] != local_bytes
    assert result["version"] == 2

    persist.reset_mock()
    gcs.uploads.clear()

    def _regen_global(*_a, **_k):
        return ImageGeneration(content=global_bytes, content_type="image/jpeg", prompt="revised")

    monkeypatch.setattr(job_service.regenerate, "regenerate_image", _regen_global)
    with pytest.raises(AttributeValueRegenerationError, match="could not be kept local"):
        job_service.regenerate_attribute_value(
            MagicMock(),
            client,
            gcs,
            value_external_id=latest.external_id,
            improvement="restyle all",
        )
    persist.assert_not_called()
    assert gcs.uploads == []


def test_text_regenerate_does_not_call_localize(monkeypatch):
    latest = SimpleNamespace(
        value="Old title",
        prompt="stored prompt",
        attribute_id=1,
        sku_generation_job_id=2,
        marketplace_id=3,
        slot=0,
        version=1,
        external_id=uuid4(),
    )
    master = SimpleNamespace(
        id=1,
        name=AttributeName.TITLE.value,
        data_type=AttributeDataType.TEXT.value,
        external_id=uuid4(),
    )
    sku_job = SimpleNamespace(id=2, job_id=4, sku_id=5, external_id=uuid4())
    job = SimpleNamespace(
        job_type="GENERATION",
        marketplace_id=uuid4(),
        brand_id=uuid4(),
        external_id=uuid4(),
    )
    monkeypatch.setattr(
        job_service.attribute_value_repo, "get_latest_by_external_id", lambda *_a, **_k: latest
    )
    monkeypatch.setattr(job_service.attribute_master_repo, "get_by_id", lambda *_a, **_k: master)
    monkeypatch.setattr(job_service.sku_generation_job_repo, "get_by_id", lambda *_a, **_k: sku_job)
    monkeypatch.setattr(job_service.job_repo, "get_by_id", lambda *_a, **_k: job)
    monkeypatch.setattr(
        job_service.brand_repo, "get_by_external_id", lambda *_a, **_k: SimpleNamespace(id=9)
    )
    monkeypatch.setattr(
        job_service.sku_master_repo, "get_by_id", lambda *_a, **_k: SimpleNamespace(deleted_at=None)
    )
    monkeypatch.setattr(job_service.inputs, "load_context", lambda *_a, **_k: SimpleNamespace())
    monkeypatch.setattr(
        job_service.regenerate,
        "revise_prompt",
        lambda *_a, **_k: SimpleNamespace(prompt="revised text prompt"),
    )
    monkeypatch.setattr(
        job_service.regenerate,
        "regenerate_text",
        lambda *_a, **_k: SimpleNamespace(value="New title", prompt="revised text prompt"),
    )
    persist = MagicMock(return_value={"external_id": latest.external_id, "version": 2})
    monkeypatch.setattr(job_service, "_persist_attribute_value", persist)
    localize = MagicMock(side_effect=AssertionError("TEXT path must not localize"))
    monkeypatch.setattr(job_service, "localize_image", localize)

    result = job_service.regenerate_attribute_value(
        MagicMock(),
        MagicMock(),
        MagicMock(),
        value_external_id=latest.external_id,
        improvement="shorter",
    )
    localize.assert_not_called()
    persist.assert_called_once()
    assert result["value"] == "New title"
    assert LOCALIZE_FAIL_MESSAGE
