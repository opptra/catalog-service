"""Generic filesystem helpers. No domain knowledge — reusable across features."""

import json
from pathlib import Path
from typing import Any

_IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: Any) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_bytes(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def extension_for_image_content_type(content_type: str) -> str:
    """Map an image content type (e.g. ``image/png``) to a file extension."""
    return _IMAGE_EXTENSIONS.get(content_type, ".png")
