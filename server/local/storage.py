"""Filesystem stand-in for GcsClient.

Same method names the pipeline already calls. GET URLs are ``data:`` so OpenRouter
can see images (it cannot fetch localhost). PUT/DELETE URLs are ``/api/local-storage/...``
for the Vite-proxied browser upload path.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.clients.gcs import UploadedObject
from core.exceptions import GcsError

_LOCAL_BUCKET = "local"
_LOCAL_API_PREFIX = "/api/local-storage"


class LocalStorageClient:
    """Store objects under ``root_dir``. Credentials are not used."""

    def __init__(self, root_dir: str | Path) -> None:
        self._root = Path(root_dir).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._bucket_name = _LOCAL_BUCKET

    def upload_bytes(
        self,
        data: bytes,
        object_name: str,
        *,
        content_type: str = "application/octet-stream",
    ) -> UploadedObject:
        path = self._resolved(object_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if content_type:
            path.with_suffix(path.suffix + ".content-type").write_text(
                content_type, encoding="utf-8"
            )
        return self._uploaded(object_name)

    def upload_file(
        self,
        path: Path,
        object_name: str,
        *,
        content_type: str | None = None,
    ) -> UploadedObject:
        data = Path(path).read_bytes()
        guessed = content_type or mimetypes.guess_type(str(path))[0]
        return self.upload_bytes(
            data,
            object_name,
            content_type=guessed or "application/octet-stream",
        )

    def upload_json(self, data: Any, object_name: str) -> UploadedObject:
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return self.upload_bytes(payload, object_name, content_type="application/json")

    def download_bytes(self, object_name: str) -> bytes:
        path = self._resolved(object_name)
        if not path.is_file():
            raise GcsError(f"Local object not found: {object_name!r}")
        return path.read_bytes()

    def object_exists(self, object_name: str) -> bool:
        return self._resolved(object_name).is_file()

    def list_object_names(self, prefix: str) -> list[str]:
        if not prefix:
            raise ValueError("prefix is required")
        names: list[str] = []
        root = self._root
        for path in root.rglob("*"):
            if not path.is_file() or path.name.endswith(".content-type"):
                continue
            if path.name.endswith(".debug.json"):
                continue
            relative = path.relative_to(root).as_posix()
            if relative.startswith(prefix):
                names.append(relative)
        return names

    def public_url(self, object_name: str) -> str:
        return f"{_LOCAL_API_PREFIX}/{quote(object_name, safe='/')}"

    def gs_uri(self, object_name: str) -> str:
        return f"gs://{self._bucket_name}/{object_name}"

    def signed_url(self, object_name: str, *, expiration_seconds: int = 3600) -> str:
        del expiration_seconds
        return self._data_url(object_name)

    def object_name_from_gs_uri(self, gs_uri: str) -> str | None:
        prefix = f"gs://{self._bucket_name}/"
        if gs_uri.startswith(prefix):
            object_name = gs_uri[len(prefix) :]
            return object_name or None
        if not gs_uri.startswith("gs://"):
            return None
        without_scheme = gs_uri[5:]
        slash = without_scheme.find("/")
        if slash < 0:
            return None
        object_name = without_scheme[slash + 1 :]
        return object_name or None

    def signed_url_for_gs_uri(self, gs_uri: str, *, expiration_seconds: int = 3600) -> str:
        object_name = self.object_name_from_gs_uri(gs_uri)
        if object_name is None:
            raise GcsError(f"Invalid local URI for signing: {gs_uri!r}")
        return self.signed_url(object_name, expiration_seconds=expiration_seconds)

    def signed_upload_url(
        self,
        object_name: str,
        *,
        content_type: str,
        expiration_seconds: int = 3600,
    ) -> str:
        del content_type, expiration_seconds
        return f"{_LOCAL_API_PREFIX}/{quote(object_name, safe='/')}"

    def signed_delete_url(self, object_name: str, *, expiration_seconds: int = 3600) -> str:
        del expiration_seconds
        return f"{_LOCAL_API_PREFIX}/{quote(object_name, safe='/')}"

    def write_debug_json(self, object_name: str, payload: dict[str, Any]) -> None:
        """Write ``{stem}.debug.json`` next to an uploaded image for local inspection."""
        path = self._resolved(object_name)
        debug_path = path.with_name(f"{path.stem}.debug.json")
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def resolve_path(self, object_name: str) -> Path:
        return self._resolved(object_name)

    def content_type_for(self, object_name: str) -> str:
        path = self._resolved(object_name)
        marker = path.with_suffix(path.suffix + ".content-type")
        if marker.is_file():
            return marker.read_text(encoding="utf-8").strip() or "application/octet-stream"
        guessed = mimetypes.guess_type(object_name)[0]
        return guessed or "application/octet-stream"

    def _data_url(self, object_name: str) -> str:
        data = self.download_bytes(object_name)
        content_type = self.content_type_for(object_name)
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{content_type};base64,{encoded}"

    def _resolved(self, object_name: str) -> Path:
        if not object_name or object_name.startswith("/") or ".." in Path(object_name).parts:
            raise GcsError(f"Invalid object name: {object_name!r}")
        path = (self._root / object_name).resolve()
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise GcsError(f"Invalid object name: {object_name!r}") from exc
        return path

    def _uploaded(self, object_name: str) -> UploadedObject:
        return UploadedObject(
            bucket=self._bucket_name,
            object_name=object_name,
            gs_uri=self.gs_uri(object_name),
            public_url=self.public_url(object_name),
        )
