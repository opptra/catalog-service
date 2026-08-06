"""Google Cloud Storage client — one shared instance for the app lifetime."""

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import google.auth
import google.auth.transport.requests
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
    (user login locally, VM service account on GCE).

    V4 signed URLs are minted via IAM SignBlob using
    ``signer_service_account_email`` (ADC rarely has a private key).
    """

    def __init__(
        self,
        bucket: str,
        *,
        project: str | None = None,
        signer_service_account_email: str | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("GCS bucket is required")
        self._bucket_name = bucket
        self._signer_service_account_email = (
            signer_service_account_email.strip() if signer_service_account_email else None
        )
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

    def download_bytes(self, object_name: str) -> bytes:
        """Download object contents."""
        if not object_name:
            raise ValueError("object_name is required")
        blob = self._bucket.blob(object_name)
        try:
            return blob.download_as_bytes()
        except GoogleCloudError as exc:
            raise GcsError(f"GCS download failed for {object_name!r}: {exc}") from exc

    def object_exists(self, object_name: str) -> bool:
        if not object_name:
            raise ValueError("object_name is required")
        blob = self._bucket.blob(object_name)
        try:
            return bool(blob.exists())
        except GoogleCloudError as exc:
            raise GcsError(f"GCS exists check failed for {object_name!r}: {exc}") from exc

    def list_object_names(self, prefix: str) -> list[str]:
        """List object names under ``prefix`` (files only, not directory placeholders)."""
        if not prefix:
            raise ValueError("prefix is required")
        try:
            blobs = self._client.list_blobs(self._bucket_name, prefix=prefix)
            return [blob.name for blob in blobs if blob.name and not blob.name.endswith("/")]
        except GoogleCloudError as exc:
            raise GcsError(f"GCS list failed for prefix {prefix!r}: {exc}") from exc

    def public_url(self, object_name: str) -> str:
        """HTTPS URL for ``object_name`` (works when the object/bucket is publicly readable)."""
        return f"https://storage.googleapis.com/{self._bucket_name}/{quote(object_name, safe='/')}"

    def gs_uri(self, object_name: str) -> str:
        return f"gs://{self._bucket_name}/{object_name}"

    def signed_url(self, object_name: str, *, expiration_seconds: int = 3600) -> str:
        """Time-limited HTTPS GET URL for a private object."""
        return self._signed_url(object_name, method="GET", expiration_seconds=expiration_seconds)

    def signed_upload_url(
        self,
        object_name: str,
        *,
        content_type: str,
        expiration_seconds: int = 3600,
    ) -> str:
        """Time-limited HTTPS PUT URL for a private object."""
        return self._signed_url(
            object_name,
            method="PUT",
            expiration_seconds=expiration_seconds,
            content_type=content_type,
        )

    def signed_delete_url(self, object_name: str, *, expiration_seconds: int = 3600) -> str:
        """Time-limited HTTPS DELETE URL for a private object."""
        return self._signed_url(
            object_name,
            method="DELETE",
            expiration_seconds=expiration_seconds,
        )

    def _signed_url(
        self,
        object_name: str,
        *,
        method: str,
        expiration_seconds: int,
        content_type: str | None = None,
    ) -> str:
        if not object_name:
            raise ValueError("object_name is required")
        if expiration_seconds <= 0:
            raise ValueError("expiration_seconds must be positive")
        signer_email = self._resolve_signer_email()
        credentials, _ = google.auth.default()
        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)
        if not credentials.token:
            raise GcsError("GCS credentials have no access token for signing")

        blob = self._bucket.blob(object_name)
        kwargs: dict[str, Any] = {
            "expiration": timedelta(seconds=expiration_seconds),
            "method": method,
            "version": "v4",
            "service_account_email": signer_email,
            "access_token": credentials.token,
        }
        if content_type is not None:
            kwargs["content_type"] = content_type
        try:
            return blob.generate_signed_url(**kwargs)
        except (AttributeError, GoogleCloudError, ValueError, TypeError) as exc:
            raise GcsError(f"GCS signed {method} URL failed for {object_name!r}: {exc}") from exc

    def _resolve_signer_email(self) -> str:
        if self._signer_service_account_email:
            return self._signer_service_account_email
        credentials, _ = google.auth.default()
        email = getattr(credentials, "service_account_email", None)
        if email and email != "default":
            return email
        raise GcsError(
            "GCS signed URLs require GCS_SIGNER_SERVICE_ACCOUNT_EMAIL "
            "(a service account email, not a user email)"
        )

    def _uploaded(self, object_name: str) -> UploadedObject:
        return UploadedObject(
            bucket=self._bucket_name,
            object_name=object_name,
            gs_uri=self.gs_uri(object_name),
            public_url=self.public_url(object_name),
        )
