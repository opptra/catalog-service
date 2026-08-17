"""Keep-frame composite: copy source pixels outside a binary delta mask."""

from io import BytesIO

from PIL import Image, ImageChops, ImageFilter

_MAX_CHANNEL_DELTA = 20
_ON_FRACTION_CEILING = 0.35
_MORPH_SIZE = 3
_THRESHOLD_LUT = [255 if i >= _MAX_CHANNEL_DELTA else 0 for i in range(256)]
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

LOCALIZE_FAIL_MESSAGE = (
    "This change could not be kept local to your notes. Try a more specific object "
    "or color, or keep the current image. Whole-scene restyles are not supported here."
)


class LocalizationImpossibleError(ValueError):
    """Raised when the candidate cannot be localized to a keep-frame edit."""


def localize_image(source_bytes: bytes, candidate_bytes: bytes) -> bytes:
    """Return PNG (or original source bytes) with unedited pixels copied from source.

    Raises ``LocalizationImpossibleError`` when bytes cannot be decoded or the
    binary mask on-fraction exceeds the keep-frame ceiling.
    """
    source = _decode_rgb(source_bytes)
    candidate = _decode_rgb(candidate_bytes)
    if candidate.size != source.size:
        candidate = candidate.resize(source.size, Image.Resampling.LANCZOS)

    mask = _binary_mask(source, candidate)
    on_fraction = _on_fraction(mask)
    if on_fraction > _ON_FRACTION_CEILING:
        raise LocalizationImpossibleError(LOCALIZE_FAIL_MESSAGE)
    if on_fraction == 0.0:
        # Identity PNG can keep original bytes; JPEG (and other) sources must
        # still be PNG because regenerate always uploads image/png.
        if source_bytes.startswith(_PNG_MAGIC):
            return source_bytes
        return _encode_png(source)

    composited = Image.composite(candidate, source, mask)
    return _encode_png(composited)


def _decode_rgb(data: bytes) -> Image.Image:
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            return image.convert("RGB")
    except Exception as exc:  # noqa: BLE001 — domain-map undecodable input
        raise LocalizationImpossibleError("undecodable image bytes") from exc


def _binary_mask(source: Image.Image, candidate: Image.Image) -> Image.Image:
    bands = ImageChops.difference(source, candidate).split()
    max_delta = bands[0]
    for band in bands[1:]:
        max_delta = ImageChops.lighter(max_delta, band)
    thresholded = max_delta.point(_THRESHOLD_LUT)
    if _on_fraction(thresholded) == 0.0:
        return thresholded
    # Close then open to drop speckle without feathering the seam.
    closed = thresholded.filter(ImageFilter.MaxFilter(_MORPH_SIZE)).filter(
        ImageFilter.MinFilter(_MORPH_SIZE)
    )
    return closed.filter(ImageFilter.MinFilter(_MORPH_SIZE)).filter(
        ImageFilter.MaxFilter(_MORPH_SIZE)
    )


def _on_fraction(mask: Image.Image) -> float:
    histogram = mask.histogram()
    on_count = sum(histogram[128:])
    total = mask.size[0] * mask.size[1]
    if total == 0:
        return 1.0
    return on_count / total


def _encode_png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
