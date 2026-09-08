"""Print TIFF / CMYK JPEG → sRGB JPEG.

Mirrors ``client/src/lib/ensureSrgbImage.ts`` and
``client/src/lib/convertCmykJpegToSrgb.ts``: same detection, same IEC sRGB ICC,
relative colorimetric + black-point compensation. The browser uses ImageMagick
WASM ``ColorTransformMode.HighRes``; this uses LittleCMS via Pillow ImageCms
with ``HIGHRESPRECALC``.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageCms

from utils.srgb_icc import SRGB_ICC

JPEG_CONTENT_TYPE = "image/jpeg"
_JPEG_QUALITY = 95
_BROWSER_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
PREVIEW_MAX_EDGE = 2048


def is_tiff(content: bytes) -> bool:
    if len(content) < 4:
        return False
    little = content[0] == 0x49 and content[1] == 0x49
    big = content[0] == 0x4D and content[1] == 0x4D
    if little and content[3] == 0x00 and content[2] in {0x2A, 0x2B}:
        return True
    return big and content[2] == 0x00 and content[3] in {0x2A, 0x2B}


def jpeg_component_count(content: bytes) -> int | None:
    if len(content) < 4 or content[0] != 0xFF or content[1] != 0xD8:
        return None
    offset = 2
    length = len(content)
    while offset < length:
        if content[offset] != 0xFF:
            offset += 1
            continue
        while offset < length and content[offset] == 0xFF:
            offset += 1
        if offset >= length:
            return None
        marker = content[offset]
        offset += 1
        if marker in {0xD8, 0xD9, 0x01}:
            continue
        if 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xDA:
            return None
        if offset + 1 >= length:
            return None
        segment = (content[offset] << 8) | content[offset + 1]
        if segment < 2 or offset + segment > length:
            return None
        is_sof = (
            (0xC0 <= marker <= 0xC3)
            or (0xC5 <= marker <= 0xC7)
            or (0xC9 <= marker <= 0xCB)
            or (0xCD <= marker <= 0xCF)
        )
        if is_sof and segment >= 8:
            return content[offset + 7]
        offset += segment
    return None


def is_cmyk_jpeg(content: bytes) -> bool:
    return jpeg_component_count(content) == 4


def needs_srgb_jpeg_convert(content: bytes) -> bool:
    return is_tiff(content) or is_cmyk_jpeg(content)


def _to_srgb(image: Image.Image, source_icc: bytes) -> Image.Image:
    source = ImageCms.ImageCmsProfile(BytesIO(source_icc))
    dest = ImageCms.ImageCmsProfile(BytesIO(SRGB_ICC))
    converted = ImageCms.profileToProfile(
        image,
        source,
        dest,
        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
        outputMode="RGB",
        flags=ImageCms.Flags.BLACKPOINTCOMPENSATION | ImageCms.Flags.HIGHRESPRECALC,
    )
    if converted is None:
        raise ValueError("Could not convert print image to sRGB")
    return converted


def _save_srgb_jpeg(image: Image.Image) -> bytes:
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    buffer = BytesIO()
    rgb.save(buffer, format="JPEG", quality=_JPEG_QUALITY, icc_profile=SRGB_ICC)
    return buffer.getvalue()


def convert_to_srgb_jpeg(content: bytes) -> bytes:
    """Convert a CMYK JPEG or any TIFF to an sRGB JPEG using the file ICC when present."""
    source_is_tiff = is_tiff(content)
    with Image.open(BytesIO(content)) as image:
        source_icc = image.info.get("icc_profile")
        if not isinstance(source_icc, bytes) or not source_icc:
            source_icc = None
        is_cmyk = image.mode.startswith("CMYK")
        if is_cmyk:
            if source_icc is not None:
                return _save_srgb_jpeg(_to_srgb(image, source_icc))
            if not source_is_tiff:
                return content
            return _save_srgb_jpeg(image.convert("RGB"))
        if source_is_tiff and source_icc is not None:
            return _save_srgb_jpeg(_to_srgb(image, source_icc))
        return _save_srgb_jpeg(image)


def _fit_max_edge_jpeg(content: bytes, max_edge: int) -> bytes:
    with Image.open(BytesIO(content)) as image:
        longest = max(image.size)
        if longest <= max_edge:
            return content
        rgb = image.convert("RGB")
        scale = max_edge / longest
        rgb = rgb.resize(
            (max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))),
            Image.Resampling.LANCZOS,
        )
        return _save_srgb_jpeg(rgb)


def for_browser_preview(
    content: bytes,
    content_type: str,
    *,
    max_edge: int = PREVIEW_MAX_EDGE,
) -> tuple[bytes, str]:
    """sRGB JPEG (or a browser-native type) for ``<img>``. Same convert as wizard upload."""
    if needs_srgb_jpeg_convert(content):
        converted = convert_to_srgb_jpeg(content)
        if is_tiff(converted) or is_cmyk_jpeg(converted):
            with Image.open(BytesIO(converted)) as image:
                content = _save_srgb_jpeg(image)
        else:
            content = converted
        content_type = JPEG_CONTENT_TYPE
    elif content_type not in _BROWSER_TYPES:
        with Image.open(BytesIO(content)) as image:
            content = _save_srgb_jpeg(image)
        content_type = JPEG_CONTENT_TYPE
    if content_type == JPEG_CONTENT_TYPE:
        content = _fit_max_edge_jpeg(content, max_edge)
    return content, content_type
