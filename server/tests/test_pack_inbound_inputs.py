from pathlib import Path

from pipelines.inbound_qc.loaders import load_sku_bundles
from pipelines.pack_inbound_inputs.drive import drive_file_id, image_suffix, looks_like_image
from pipelines.pack_inbound_inputs.pack import (
    build_rows,
    load_table,
    pack_inbound_inputs,
)


class FakeDrive:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.downloaded: list[str] = []

    def download(self, file_id: str) -> bytes:
        self.downloaded.append(file_id)
        return self.files[file_id]


def test_drive_file_id_from_share_link() -> None:
    url = "https://drive.google.com/file/d/131gMVU7lrQnX5L51rxSbSpObIXePbzlB/view?usp=sharing"
    assert drive_file_id(url) == "131gMVU7lrQnX5L51rxSbSpObIXePbzlB"
    assert drive_file_id("") is None


def test_looks_like_image() -> None:
    jpeg = b"\xff\xd8\xff" + b"\x00" * 20
    tiff = b"II*\x00" + b"\x00" * 20
    assert looks_like_image(jpeg) is True
    assert looks_like_image(tiff) is True
    assert image_suffix(tiff) == ".tif"
    assert looks_like_image(b"<html>login</html>") is False


def test_load_table_renames_duplicate_headers(tmp_path: Path) -> None:
    path = tmp_path / "details.csv"
    path.write_text(
        "Opptra SKU,Product Description,Product Description,Color\n"
        "SKU-A,Long copy,INTERNAL NAME,Red\n",
        encoding="utf-8",
    )
    rows = load_table(path)
    assert rows[0]["Product Description"] == "Long copy"
    assert rows[0]["Product Description (2)"] == "INTERNAL NAME"


def test_build_rows_joins_on_opptra_sku_and_keeps_split_only() -> None:
    details = [
        {
            "Opptra SKU": "SKU-A",
            "Title": "Red Double Bedsheet",
            "Product Description": "Long copy",
            "Product Name": "Bed Sheet Set",
            "Product Description (2)": "INTERNAL",
            "Color": "Red",
            "S/D/K/SK": "Double",
            "Size": "224X244",
            "Design Style": "Floral",
            "Material": "Cotton",
            "Sub Category": "Bedsheet Set",
            "EAN": "123",
            "Image drive link  -1": "https://drive.google.com/file/d/detail1/view",
        }
    ]
    split = [
        {
            "Opptra SKU": "SKU-A",
            "EAN": "123",
            "Sub Category": "Bedsheet",
            "Image Link 1": "https://drive.google.com/file/d/split1/view",
            "Image Link 2": "https://drive.google.com/file/d/split2/view",
        },
        {
            "Opptra SKU": "SKU-B",
            "EAN": "999",
            "Brand": "Bombay Dyeing",
            "Sub Category": "Bedsheet",
            "Image Link 1": "https://drive.google.com/file/d/splitb/view",
        },
    ]
    rows, images, urls = build_rows(details, split)
    assert [row["SKU"] for row in rows] == ["SKU-A", "SKU-B"]
    assert rows[0]["Product Name / Title"] == "Red Double Bedsheet"
    assert rows[0]["Size"] == "Double"
    assert rows[0]["Bed Size"] == "Double"
    assert rows[0]["Bedsheet Size"] == "224X244"
    assert rows[0]["Pattern"] == "Floral"
    assert rows[0]["Product Type"] == "Bedsheet Set"
    assert rows[0]["Product Name"] == "Bed Sheet Set"
    assert rows[1]["Brand Name"] == "Bombay Dyeing"
    assert images["SKU-A"] == ["split1", "split2", "detail1"]
    assert images["SKU-B"] == ["splitb"]
    assert urls["SKU-A"] == [
        "https://drive.google.com/file/d/split1/view",
        "https://drive.google.com/file/d/split2/view",
        "https://drive.google.com/file/d/detail1/view",
    ]
    assert urls["SKU-B"] == ["https://drive.google.com/file/d/splitb/view"]


def test_pack_writes_wizard_layout(tmp_path: Path) -> None:
    details = tmp_path / "details.csv"
    split = tmp_path / "split.csv"
    details.write_text(
        "Opptra SKU,Title,Product Description,Color,S/D/K/SK,Size,Design Style,"
        "Material,Sub Category,EAN\n"
        "SKU-A,Red sheet,Desc,Red,Double,224X244,Floral,Cotton,Bedsheet Set,123\n",
        encoding="utf-8",
    )
    split.write_text(
        "Opptra SKU,EAN,Sub Category,Image Link 1\n"
        "SKU-A,123,Bedsheet,https://drive.google.com/file/d/abc/view\n",
        encoding="utf-8",
    )
    jpeg = b"\xff\xd8\xff" + b"\x00" * 32
    out = tmp_path / "out"
    result = pack_inbound_inputs(
        details,
        split,
        out,
        store=FakeDrive({"abc": jpeg}),
        workers=1,
        cache_dir=tmp_path / "cache",
    )
    assert result.attributes_csv.is_file()
    bundles = load_sku_bundles(result.attributes_csv, result.images_zip)
    assert len(bundles) == 1
    assert bundles[0].sku_id == "SKU-A"
    assert bundles[0].attributes["Color"] == "Red"
    assert bundles[0].attributes["Size"] == "Double"
    assert [image.filename for image in bundles[0].images] == ["image_01.jpg"]
    links = (out / "image_links.csv").read_text(encoding="utf-8-sig")
    assert "https://drive.google.com/file/d/abc/view" in links


def test_pack_resumes_from_drive_cache(tmp_path: Path) -> None:
    details = tmp_path / "details.csv"
    split = tmp_path / "split.csv"
    details.write_text("Opptra SKU,Title,Color\nSKU-A,Name,Red\n", encoding="utf-8")
    split.write_text(
        "Opptra SKU,EAN,Image Link 1\nSKU-A,123,https://drive.google.com/file/d/abc/view\n",
        encoding="utf-8",
    )
    jpeg = b"\xff\xd8\xff" + b"\x00" * 32
    cache = tmp_path / "cache"
    first = FakeDrive({"abc": jpeg})
    pack_inbound_inputs(details, split, tmp_path / "out1", store=first, workers=1, cache_dir=cache)
    assert first.downloaded == ["abc"]
    second = FakeDrive({"abc": jpeg})
    result = pack_inbound_inputs(
        details, split, tmp_path / "out2", store=second, workers=1, cache_dir=cache
    )
    assert second.downloaded == []
    bundles = load_sku_bundles(result.attributes_csv, result.images_zip)
    assert [image.filename for image in bundles[0].images] == ["image_01.jpg"]


def test_pack_skip_images_writes_csv(tmp_path: Path) -> None:
    details = tmp_path / "details.csv"
    split = tmp_path / "split.csv"
    details.write_text("Opptra SKU,Title,Color\nSKU-A,Name,Red\n", encoding="utf-8")
    split.write_text("Opptra SKU,EAN\nSKU-A,123\n", encoding="utf-8")
    result = pack_inbound_inputs(
        details,
        split,
        tmp_path / "out",
        skip_images=True,
    )
    assert result.sku_ids == ("SKU-A",)
    assert result.attributes_csv.read_text(encoding="utf-8-sig").startswith("SKU,")
    assert result.failures_csv.is_file()
    assert "no_images" in result.failures_csv.read_text(encoding="utf-8-sig")


def test_pack_writes_failures_report(tmp_path: Path) -> None:
    details = tmp_path / "details.csv"
    split = tmp_path / "split.csv"
    details.write_text(
        "Opptra SKU,Title,Color\nSKU-A,Name,Red\nSKU-B,Other,Blue\n",
        encoding="utf-8",
    )
    split.write_text(
        "Opptra SKU,EAN,Image Link 1\n"
        "SKU-A,123,https://drive.google.com/file/d/good/view\n"
        "SKU-B,456,https://drive.google.com/file/d/bad/view\n",
        encoding="utf-8",
    )
    jpeg = b"\xff\xd8\xff" + b"\x00" * 32

    class PartialDrive:
        def download(self, file_id: str) -> bytes:
            if file_id == "bad":
                raise RuntimeError("timed out")
            return jpeg

    result = pack_inbound_inputs(
        details,
        split,
        tmp_path / "out",
        store=PartialDrive(),
        workers=1,
        cache_dir=tmp_path / "cache",
    )
    assert result.missing_image_sku_ids == ("SKU-B",)
    rows = result.failures_csv.read_text(encoding="utf-8-sig").splitlines()
    assert rows[0] == "sku,status,drive_file_id,error,no_images"
    assert "SKU-B,failed,bad,timed out,yes" in rows
