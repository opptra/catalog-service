"""Wizard TIFF / CMYK JPEG → sRGB JPEG (same rules as client Magick convert)."""

from io import BytesIO

from PIL import Image

from utils.srgb_icc import SRGB_ICC
from utils.srgb_jpeg import (
    JPEG_CONTENT_TYPE,
    PREVIEW_MAX_EDGE,
    convert_to_srgb_jpeg,
    for_browser_preview,
    is_cmyk_jpeg,
    is_tiff,
    needs_srgb_jpeg_convert,
)


def _cmyk_jpeg() -> bytes:
    buffer = BytesIO()
    Image.new("CMYK", (8, 8), (10, 20, 30, 40)).save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def test_detects_tiff_magic() -> None:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buffer, format="TIFF")
    content = buffer.getvalue()
    assert is_tiff(content)
    assert needs_srgb_jpeg_convert(content)
    assert not is_tiff(_cmyk_jpeg())


def test_cmyk_jpeg_without_icc_is_unchanged() -> None:
    content = _cmyk_jpeg()
    assert is_cmyk_jpeg(content)
    assert needs_srgb_jpeg_convert(content)
    converted = convert_to_srgb_jpeg(content)
    assert converted is content


def test_tiff_converts_to_srgb_jpeg() -> None:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), (200, 10, 10)).save(buffer, format="TIFF")
    jpeg = convert_to_srgb_jpeg(buffer.getvalue())
    assert jpeg[:3] == b"\xff\xd8\xff"
    with Image.open(BytesIO(jpeg)) as image:
        assert image.mode == "RGB"
        assert image.size == (16, 12)


def test_tiff_with_icc_converts_to_srgb_jpeg() -> None:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (0, 128, 255)).save(buffer, format="TIFF", icc_profile=SRGB_ICC)
    jpeg = convert_to_srgb_jpeg(buffer.getvalue())
    assert jpeg[:3] == b"\xff\xd8\xff"
    with Image.open(BytesIO(jpeg)) as image:
        assert image.info.get("icc_profile") == SRGB_ICC


def test_cmyk_tiff_without_icc_becomes_jpeg() -> None:
    buffer = BytesIO()
    Image.new("CMYK", (8, 8), (0, 80, 80, 0)).save(buffer, format="TIFF")
    jpeg = convert_to_srgb_jpeg(buffer.getvalue())
    assert jpeg[:3] == b"\xff\xd8\xff"
    with Image.open(BytesIO(jpeg)) as image:
        assert image.mode == "RGB"


def test_browser_preview_converts_tiff_and_caps_edge() -> None:
    buffer = BytesIO()
    Image.new("RGB", (PREVIEW_MAX_EDGE + 400, 80), (12, 34, 56)).save(buffer, format="TIFF")
    jpeg, content_type = for_browser_preview(buffer.getvalue(), "image/tiff")
    assert content_type == JPEG_CONTENT_TYPE
    assert jpeg[:3] == b"\xff\xd8\xff"
    with Image.open(BytesIO(jpeg)) as image:
        assert max(image.size) == PREVIEW_MAX_EDGE


def test_browser_preview_flattens_cmyk_jpeg_without_icc() -> None:
    content = _cmyk_jpeg()
    jpeg, content_type = for_browser_preview(content, "image/jpeg")
    assert content_type == JPEG_CONTENT_TYPE
    assert jpeg != content
    assert not is_cmyk_jpeg(jpeg)
