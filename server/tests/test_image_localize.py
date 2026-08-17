from io import BytesIO

import pytest
from PIL import Image

from pipelines.generation.localize import (
    LocalizationImpossibleError,
    localize_image,
)


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def _pixels(data: bytes) -> list[tuple[int, int, int]]:
    with Image.open(BytesIO(data)) as image:
        return list(image.convert("RGB").getdata())


def _solid(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", size, color)


def test_localizes_solid_rectangle_and_keeps_source_outside():
    source = _solid((32, 32), (200, 40, 40))
    candidate = source.copy()
    candidate.paste((20, 20, 180), (8, 8, 20, 20))

    result = localize_image(_png_bytes(source), _png_bytes(candidate))
    result_pixels = _pixels(result)
    source_pixels = list(source.getdata())
    candidate_pixels = list(candidate.getdata())

    for index, (out, src, cand) in enumerate(
        zip(result_pixels, source_pixels, candidate_pixels, strict=True)
    ):
        x, y = index % 32, index // 32
        if 8 <= x < 20 and 8 <= y < 20:
            assert out == cand
        else:
            assert out == src


def test_identical_images_return_original_source_bytes():
    source_bytes = _png_bytes(_solid((16, 16), (12, 34, 56)))
    assert localize_image(source_bytes, source_bytes) == source_bytes


def test_identical_jpeg_source_returns_png_bytes():
    buffer = BytesIO()
    _solid((16, 16), (12, 34, 56)).save(buffer, format="JPEG", quality=90)
    jpeg_bytes = buffer.getvalue()
    assert jpeg_bytes[:2] == b"\xff\xd8"

    result = localize_image(jpeg_bytes, jpeg_bytes)
    assert result.startswith(b"\x89PNG")
    with Image.open(BytesIO(jpeg_bytes)) as source:
        assert _pixels(result) == list(source.convert("RGB").getdata())


def test_size_mismatch_resizes_candidate_then_localizes_rectangle():
    source = _solid((32, 32), (10, 10, 10))
    candidate = _solid((16, 16), (10, 10, 10))
    candidate.paste((240, 240, 10), (4, 4, 10, 10))

    result_pixels = _pixels(localize_image(_png_bytes(source), _png_bytes(candidate)))
    source_pixels = list(source.getdata())
    changed = [
        i
        for i, (out, src) in enumerate(zip(result_pixels, source_pixels, strict=True))
        if out != src
    ]
    assert changed
    assert len(changed) / (32 * 32) < 0.35
    for index in changed:
        x, y = index % 32, index // 32
        assert 6 <= x <= 22
        assert 6 <= y <= 22


def test_faint_requested_rectangle_still_appears_in_composite():
    source = _solid((24, 24), (80, 80, 80))
    candidate = source.copy()
    candidate.paste((80, 80, 110), (6, 6, 18, 18))

    result_pixels = _pixels(localize_image(_png_bytes(source), _png_bytes(candidate)))
    source_pixels = list(source.getdata())
    inside = [
        result_pixels[y * 24 + x] != source_pixels[y * 24 + x]
        for y in range(6, 18)
        for x in range(6, 18)
    ]
    assert any(inside)


def test_globally_shifted_candidate_raises():
    source = _solid((16, 16), (30, 30, 30))
    candidate = _solid((16, 16), (200, 10, 10))
    with pytest.raises(LocalizationImpossibleError):
        localize_image(_png_bytes(source), _png_bytes(candidate))


def test_undecodable_bytes_raise():
    source = _png_bytes(_solid((8, 8), (1, 2, 3)))
    with pytest.raises(LocalizationImpossibleError):
        localize_image(source, b"not-an-image")
    with pytest.raises(LocalizationImpossibleError):
        localize_image(b"also-not-an-image", source)
