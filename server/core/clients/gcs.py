"""Google Cloud Storage client — one shared instance for the app lifetime."""

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from google.cloud import storage
from google.cloud.exceptions import GoogleCloudError

from core.exceptions import GcsError


@dataclass(frozen=True, slots=True)
class UploadedObject:
    """Result of uploading bytes/file to the configured bucket."""

    bucket: str
    object_name: str
    gs_uri: str
    public_url: str


class GcsClient:
    """Upload objects and return stable links. Credentials come from ADC
    (``GOOGLE_APPLICATION_CREDENTIALS`` locally, the VM service account on GCE).
    """

    def __init__(self, bucket: str, *, project: str | None = None) -> None:
        if not bucket:
            raise ValueError("GCS bucket is required")
        self._bucket_name = bucket
        self._client = storage.Client(project=project) if project else storage.Client()
        self._bucket = self._client.bucket(bucket)

    def upload_bytes(
        self,
        data: bytes,
        object_name: str,
        *,
        content_type: str = "application/octet-stream",
    ) -> UploadedObject:
        """Store ``data`` at ``object_name`` and return gs:// + HTTPS links."""
        if not object_name:
            raise ValueError("object_name is required")
        blob = self._bucket.blob(object_name)
        try:
            blob.upload_from_string(data, content_type=content_type)
        except GoogleCloudError as exc:
            raise GcsError(f"GCS upload failed for {object_name!r}: {exc}") from exc
        return self._uploaded(object_name)

    def upload_file(
        self,
        path: Path,
        object_name: str,
        *,
        content_type: str | None = None,
    ) -> UploadedObject:
        """Upload a local file and return gs:// + HTTPS links."""
        if not object_name:
            raise ValueError("object_name is required")
        blob = self._bucket.blob(object_name)
        try:
            blob.upload_from_filename(str(path), content_type=content_type)
        except (OSError, GoogleCloudError) as exc:
            raise GcsError(f"GCS file upload failed for {object_name!r}: {exc}") from exc
        return self._uploaded(object_name)

    def upload_json(self, data: Any, object_name: str) -> UploadedObject:
        """Serialize ``data`` as UTF-8 JSON and upload it."""
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return self.upload_bytes(payload, object_name, content_type="application/json")

    def public_url(self, object_name: str) -> str:
        """HTTPS URL for ``object_name`` (works when the object/bucket is publicly readable)."""
        return (
            f"https://storage.googleapis.com/{self._bucket_name}/"
            f"{quote(object_name, safe='/')}"
        )

    def gs_uri(self, object_name: str) -> str:
        return f"gs://{self._bucket_name}/{object_name}"

    def signed_url(self, object_name: str, *, expiration_seconds: int = 3600) -> str:
        """Time-limited HTTPS URL for a private object."""
        if expiration_seconds <= 0:
            raise ValueError("expiration_seconds must be positive")
        blob = self._bucket.blob(object_name)
        try:
            return blob.generate_signed_url(
                expiration=timedelta(seconds=expiration_seconds),
                method="GET",
                version="v4",
            )
        except GoogleCloudError as exc:
            raise GcsError(f"GCS signed URL failed for {object_name!r}: {exc}") from exc

    def _uploaded(self, object_name: str) -> UploadedObject:
        return UploadedObject(
            bucket=self._bucket_name,
            object_name=object_name,
            gs_uri=self.gs_uri(object_name),
            public_url=self.public_url(object_name),
        )
