import json
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from core.clients.openrouter import GeneratedImage
from core.config import settings
from core.exceptions import GenerateError

_LOCAL_LOGO = Path("data/generate-pipeline/v1/assets/cortina_logo.png")


def _output_root() -> Path:
    root = Path(settings.generate_output_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    return root


def extension_for_content_type(content_type: str) -> str:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
    }
    return mapping.get(content_type.lower(), ".png")


@lru_cache(maxsize=1)
def _load_logo_rgba(logo_url: str) -> Image.Image:
    """Prefer local Brand DNA logo asset; fall back to URL download."""
    local = _LOCAL_LOGO if _LOCAL_LOGO.is_absolute() else Path.cwd() / _LOCAL_LOGO
    if local.exists():
        logo = Image.open(local).convert("RGBA")
    else:
        try:
            response = httpx.get(logo_url, timeout=30.0, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GenerateError(f"Failed to download brand logo: {logo_url}") from exc
        logo = Image.open(BytesIO(response.content)).convert("RGBA")
    if logo.width < 8 or logo.height < 8:
        raise GenerateError("Brand logo asset is empty or invalid")
    return logo


def stamp_official_logo(
    image_bytes: bytes,
    *,
    logo_url: str,
    content_type: str = "image/png",
    max_logo_width_ratio: float = 0.18,
    margin_ratio: float = 0.03,
) -> GeneratedImage:
    """Paste the real Brand DNA logo (top-left). Do not trust the model to redraw it."""
    del content_type  # output always PNG after stamp
    base = Image.open(BytesIO(image_bytes)).convert("RGBA")
    logo = _load_logo_rgba(logo_url)

    target_w = max(48, int(base.width * max_logo_width_ratio))
    scale = target_w / logo.width
    target_h = max(1, int(logo.height * scale))
    logo_resized = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)

    margin = max(8, int(min(base.width, base.height) * margin_ratio))
    base.alpha_composite(logo_resized, dest=(margin, margin))

    out = BytesIO()
    base.convert("RGBA").save(out, format="PNG")
    return GeneratedImage(content=out.getvalue(), content_type="image/png")


def save_generated_image(
    *,
    run_id: str,
    product_key: str,
    image_type: str,
    variant: int,
    image: GeneratedImage,
) -> tuple[str, str]:
    """Save image bytes locally and return (relative_path, public_url)."""
    ext = extension_for_content_type(image.content_type)
    relative = Path(run_id) / product_key / f"{image_type}_v{variant}{ext}"
    absolute = _output_root() / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_bytes(image.content)
    relative_posix = relative.as_posix()
    return relative_posix, f"/api/assets/{relative_posix}"


def save_json_artifact(
    *,
    run_id: str,
    product_key: str,
    stem: str,
    payload: dict[str, Any],
) -> str:
    """Save a JSON artifact under the run folder; return relative path."""
    relative = Path(run_id) / product_key / f"{stem}.json"
    absolute = _output_root() / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return relative.as_posix()
