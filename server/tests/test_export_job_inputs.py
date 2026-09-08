from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from core.exceptions.export_job_inputs import JobInputExportError
from entities.catalog.sku_master import SkuMaster
from pipelines.export_job_inputs import export as export_mod
from pipelines.export_job_inputs.export import (
    download_sku_images,
    export_job_inputs,
    load_job_skus,
    rows_from_skus,
    write_attributes_csv,
    write_images_zip,
)
from pipelines.inbound_qc.loaders import load_sku_bundles


class FakeGcs:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.listed_prefixes: list[str] = []

    def list_object_names(self, prefix: str) -> list[str]:
        self.listed_prefixes.append(prefix)
        return [name for name in self.objects if name.startswith(prefix) and not name.endswith("/")]

    def download_bytes(self, object_name: str) -> bytes:
        return self.objects[object_name]


def _sku(pk: int, attributes: dict[str, str]) -> SkuMaster:
    sku = SkuMaster(category_id=1, attributes=attributes)
    sku.id = pk
    return sku


def test_rows_from_skus_puts_sku_first_and_unions_keys() -> None:
    headers, rows = rows_from_skus(
        [
            _sku(1, {"Color": "White", "SKU": "A", "Size": "King"}),
            _sku(2, {"SKU": "B", "Material": "Cotton", "Color": "Navy"}),
        ]
    )
    assert headers[0] == "SKU"
    assert headers == ["SKU", "Color", "Size", "Material"]
    assert rows[0]["SKU"] == "A"
    assert rows[1]["Material"] == "Cotton"
    assert rows[0].get("Material") is None


def test_rows_from_skus_skips_missing_business_sku() -> None:
    headers, rows = rows_from_skus(
        [
            _sku(1, {"Color": "White"}),
            _sku(2, {"SKU": "B", "Color": "Navy"}),
        ]
    )
    assert headers == ["SKU", "Color"]
    assert [row["SKU"] for row in rows] == ["B"]


def test_rows_from_skus_skips_invalid_sku_path() -> None:
    headers, rows = rows_from_skus(
        [
            _sku(1, {"SKU": "bad/id", "Color": "White"}),
            _sku(2, {"SKU": "GOOD", "Color": "Navy"}),
        ]
    )
    assert [row["SKU"] for row in rows] == ["GOOD"]
    assert headers == ["SKU", "Color"]


def test_rows_from_skus_errors_when_none_have_sku() -> None:
    with pytest.raises(JobInputExportError, match="attributes.SKU"):
        rows_from_skus([_sku(1, {"Color": "White"})])


def test_written_bundle_roundtrips_wizard_loader_single_sku(tmp_path: Path) -> None:
    headers = ["SKU", "Color"]
    rows = [{"SKU": "COR-1", "Color": "White"}]
    images = {"COR-1": [("image_01.jpg", b"jpeg-one")]}
    csv_path = write_attributes_csv(tmp_path / "attributes.csv", headers, rows)
    zip_path = write_images_zip(tmp_path / "images.zip", images)

    bundles = load_sku_bundles(csv_path, zip_path)
    assert [bundle.sku_id for bundle in bundles] == ["COR-1"]
    assert [image.filename for image in bundles[0].images] == ["image_01.jpg"]
    assert bundles[0].images[0].content == b"jpeg-one"


def test_written_bundle_roundtrips_wizard_loader(tmp_path: Path) -> None:
    headers = ["SKU", "Color", "Size"]
    rows = [
        {"SKU": "COR-1", "Color": "White", "Size": "King"},
        {"SKU": "COR-2", "Color": "Navy", "Size": "Queen"},
    ]
    images = {
        "COR-1": [("image_01.jpg", b"jpeg-one"), ("image_02.jpg", b"jpeg-two")],
        "COR-2": [("photo.png", b"png-bytes")],
    }
    csv_path = write_attributes_csv(tmp_path / "attributes.csv", headers, rows)
    zip_path = write_images_zip(tmp_path / "images.zip", images)

    bundles = load_sku_bundles(csv_path, zip_path)
    assert [bundle.sku_id for bundle in bundles] == ["COR-1", "COR-2"]
    assert bundles[0].attributes["Color"] == "White"
    assert [image.filename for image in bundles[0].images] == ["image_01.jpg", "image_02.jpg"]
    assert bundles[0].images[0].content == b"jpeg-one"
    assert [image.filename for image in bundles[1].images] == ["photo.png"]


def test_download_sku_images_uses_product_prefix() -> None:
    gcs = FakeGcs(
        {
            "products/COR-1/assets/images/image_01.jpg": b"one",
            "products/COR-1/assets/images/image_02.jpg": b"two",
            "products/COR-2/assets/images/other.jpg": b"nope",
            "jobs/abc/sku_generation_jobs/xyz/images/A_PLUS_1.png": b"generated",
        }
    )
    files = download_sku_images(gcs, "COR-1")
    assert files == [("image_01.jpg", b"one"), ("image_02.jpg", b"two")]


def test_export_job_inputs_writes_csv_and_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = uuid4()
    job = SimpleNamespace(id=7, external_id=job_id, job_type="GENERATION")
    sku = _sku(10, {"SKU": "COR-1", "Color": "White"})

    monkeypatch.setattr(export_mod.job_repo, "get_by_external_id", lambda session, ext: job)
    monkeypatch.setattr(
        export_mod.sku_generation_job_repo,
        "list_by_job_id",
        lambda session, pk: [SimpleNamespace(sku_id=10)],
    )
    monkeypatch.setattr(
        export_mod.sku_master_repo,
        "list_by_ids",
        lambda session, ids: [sku],
    )

    gcs = FakeGcs({"products/COR-1/assets/images/image_01.jpg": b"jpeg"})
    result = export_job_inputs(MagicMock(), gcs, job_id, tmp_path)

    assert result.sku_ids == ("COR-1",)
    assert result.attributes_csv.name == "attributes.csv"
    assert result.images_zip.name == "images.zip"
    assert result.missing_image_sku_ids == ()
    bundles = load_sku_bundles(result.attributes_csv, result.images_zip)
    assert bundles[0].sku_id == "COR-1"
    assert bundles[0].images[0].content == b"jpeg"


def test_export_job_inputs_records_skus_without_photos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = uuid4()
    job = SimpleNamespace(id=7, external_id=job_id, job_type="GENERATION")
    sku_with = _sku(10, {"SKU": "COR-1", "Color": "White"})
    sku_without = _sku(11, {"SKU": "COR-2", "Color": "Navy"})

    monkeypatch.setattr(export_mod.job_repo, "get_by_external_id", lambda session, ext: job)
    monkeypatch.setattr(
        export_mod.sku_generation_job_repo,
        "list_by_job_id",
        lambda session, pk: [SimpleNamespace(sku_id=10), SimpleNamespace(sku_id=11)],
    )
    monkeypatch.setattr(
        export_mod.sku_master_repo,
        "list_by_ids",
        lambda session, ids: [sku_with, sku_without],
    )

    gcs = FakeGcs({"products/COR-1/assets/images/image_01.jpg": b"jpeg"})
    result = export_job_inputs(MagicMock(), gcs, job_id, tmp_path)

    assert result.sku_ids == ("COR-1", "COR-2")
    assert result.missing_image_sku_ids == ("COR-2",)
    bundles = load_sku_bundles(result.attributes_csv, result.images_zip)
    assert [bundle.sku_id for bundle in bundles] == ["COR-1", "COR-2"]
    assert bundles[0].images[0].content == b"jpeg"
    assert bundles[1].images == ()


def test_export_job_inputs_limit_takes_first_n(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = uuid4()
    job = SimpleNamespace(id=7, external_id=job_id, job_type="GENERATION")
    first = _sku(10, {"SKU": "COR-1", "Color": "White"})
    second = _sku(11, {"SKU": "COR-2", "Color": "Navy"})

    monkeypatch.setattr(export_mod.job_repo, "get_by_external_id", lambda session, ext: job)
    monkeypatch.setattr(
        export_mod.sku_generation_job_repo,
        "list_by_job_id",
        lambda session, pk: [SimpleNamespace(sku_id=10), SimpleNamespace(sku_id=11)],
    )
    monkeypatch.setattr(
        export_mod.sku_master_repo,
        "list_by_ids",
        lambda session, ids: [first, second],
    )

    gcs = FakeGcs(
        {
            "products/COR-1/assets/images/image_01.jpg": b"one",
            "products/COR-2/assets/images/image_01.jpg": b"two",
        }
    )
    result = export_job_inputs(MagicMock(), gcs, job_id, tmp_path, limit=1)

    assert result.sku_ids == ("COR-1",)
    assert gcs.listed_prefixes == ["products/COR-1/assets/images/"]
    bundles = load_sku_bundles(result.attributes_csv, result.images_zip)
    assert [bundle.sku_id for bundle in bundles] == ["COR-1"]


def test_export_job_inputs_rejects_non_positive_limit(tmp_path: Path) -> None:
    with pytest.raises(JobInputExportError, match="positive"):
        export_job_inputs(MagicMock(), FakeGcs({}), uuid4(), tmp_path, limit=0)


def test_load_job_skus_rejects_flatfile_job(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = uuid4()
    monkeypatch.setattr(
        export_mod.job_repo,
        "get_by_external_id",
        lambda session, ext: SimpleNamespace(id=1, external_id=job_id, job_type="FLATFILE_UPLOAD"),
    )
    with pytest.raises(JobInputExportError, match="GENERATION"):
        load_job_skus(MagicMock(), job_id)


def test_cli_parses_limit() -> None:
    from pipelines.export_job_inputs.cli import _parse_args

    job_id = str(uuid4())
    args = _parse_args(["--job-id", job_id, "--limit", "5"])
    assert args.limit == 5
    assert str(args.job_id) == job_id
