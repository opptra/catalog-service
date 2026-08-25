from pathlib import Path

import pytest

from core.exceptions import GcsError
from local.storage import LocalStorageClient


def test_upload_download_and_data_url(tmp_path: Path) -> None:
    client = LocalStorageClient(tmp_path)
    uploaded = client.upload_bytes(b"hello", "products/sku/a.png", content_type="image/png")
    assert uploaded.gs_uri == "gs://local/products/sku/a.png"
    assert client.download_bytes("products/sku/a.png") == b"hello"
    assert client.object_exists("products/sku/a.png")
    url = client.signed_url("products/sku/a.png")
    assert url.startswith("data:image/png;base64,")
    assert client.list_object_names("products/") == ["products/sku/a.png"]


def test_rejects_path_escape(tmp_path: Path) -> None:
    client = LocalStorageClient(tmp_path)
    with pytest.raises(GcsError):
        client.upload_bytes(b"x", "../outside.bin")


def test_write_debug_json(tmp_path: Path) -> None:
    client = LocalStorageClient(tmp_path)
    client.upload_bytes(b"img", "jobs/j/images/IMAGE_1.png", content_type="image/png")
    client.write_debug_json("jobs/j/images/IMAGE_1.png", {"slot": 1})
    debug = tmp_path / "jobs/j/images/IMAGE_1.debug.json"
    assert debug.is_file()
    assert "slot" in debug.read_text(encoding="utf-8")
