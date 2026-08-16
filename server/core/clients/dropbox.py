"""Dropbox client — upload bytes and return a durable public HTTPS URL."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from core.exceptions import DropboxError

logger = logging.getLogger(__name__)

_API_BASE = "https://api.dropboxapi.com/2"
_CONTENT_BASE = "https://content.dropboxapi.com/2"
_TOKEN_URL = "https://api.dropbox.com/oauth2/token"
# Refresh a bit before Dropbox's expires_in so in-flight calls don't race expiry.
_EXPIRY_SKEW_SECONDS = 60.0

# Cap concurrent ensure/upload work across listing fill + content export.
# Warm path is one list_shared_links; cold is upload + share.
MAX_CONCURRENT_OPS = 8


@dataclass(frozen=True, slots=True)
class DropboxUploadedObject:
    """Result of uploading bytes to Dropbox."""

    path: str
    shared_url: str


class DropboxClient:
    """One shared Dropbox HTTP client for the app lifetime.

    Auth: stores ``app_key`` / ``app_secret`` / ``refresh_token`` from settings.
    Short-lived access tokens are fetched via OAuth refresh and kept in memory
    only — never written back to env. Refresh happens lazily on first use and
    again when the cached token is near expiry or Dropbox returns 401.

    Upload path is under ``root_path``; shared links are converted to direct
    ``dl=1`` URLs suitable for Amazon flat-file image cells.

    ``ensure_shared_url`` is the product entry point: ``list_shared_links`` on the
    deterministic path → upload only on miss. Concurrent ensures are capped by
    ``max_concurrent_ops``.
    """

    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        refresh_token: str,
        root_path: str = "/catalog-service/listing-images",
        timeout: float = 120.0,
        max_concurrent_ops: int = MAX_CONCURRENT_OPS,
    ) -> None:
        if not app_key or not app_secret or not refresh_token:
            raise ValueError("Dropbox app_key, app_secret, and refresh_token are required")
        if max_concurrent_ops < 1:
            raise ValueError("max_concurrent_ops must be >= 1")
        self._app_key = app_key
        self._app_secret = app_secret
        self._refresh_token = refresh_token
        self._root_path = root_path.rstrip("/") or "/catalog-service/listing-images"
        self._http = httpx.Client(timeout=timeout)
        self._token_lock = threading.Lock()
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0
        self.max_concurrent_ops = max_concurrent_ops
        self._op_semaphore = threading.Semaphore(max_concurrent_ops)

    def close(self) -> None:
        self._http.close()

    def ensure_shared_url(
        self,
        *,
        relative_dir: str,
        filename: str,
        load_bytes: Callable[[], bytes],
    ) -> str:
        """Return a durable ``dl=1`` URL for ``{relative_dir}/{filename}``.

        Warm path (file+link already on Dropbox): one ``list_shared_links``.
        Cold path: upload bytes, then create (or reuse) a shared link.

        Dropbox does not return a shared URL from upload alone — link creation is
        separate — but we do not ``list_folder`` first; the path is deterministic.
        """
        if not relative_dir:
            raise ValueError("relative_dir is required")
        if not filename:
            raise ValueError("filename is required")
        path = f"{self._root_path}/{relative_dir.lstrip('/')}/{filename.lstrip('/')}"

        with self._op_semaphore:
            existing = self._list_shared_link_url(path)
            if existing:
                return self._as_direct_url(existing)

            data = load_bytes()
            self._upload_bytes_at(path, data)
            return self._as_direct_url(self._create_or_get_shared_link(path))

    def upload_bytes(
        self,
        data: bytes,
        relative_path: str,
    ) -> DropboxUploadedObject:
        """Upload ``data`` and return a durable shared HTTPS URL (``dl=1``).

        Prefer ``ensure_shared_url`` from product flows so existence is checked
        without re-uploading.
        """
        if not relative_path:
            raise ValueError("relative_path is required")
        path = f"{self._root_path}/{relative_path.lstrip('/')}"
        with self._op_semaphore:
            self._upload_bytes_at(path, data)
            url = self._as_direct_url(self._create_or_get_shared_link(path))
            return DropboxUploadedObject(path=path, shared_url=url)

    def _upload_bytes_at(self, path: str, data: bytes) -> None:
        response = self._request(
            "POST",
            f"{_CONTENT_BASE}/files/upload",
            headers={
                "Dropbox-API-Arg": json.dumps(
                    {
                        "path": path,
                        "mode": "overwrite",
                        "autorename": False,
                        "mute": True,
                    }
                ),
                "Content-Type": "application/octet-stream",
            },
            content=data,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DropboxError(f"Dropbox upload failed for {path!r}: {exc}") from exc

    @staticmethod
    def _as_direct_url(shared_url: str) -> str:
        """Prefer a direct-download form Amazon can fetch without a preview page."""
        direct = shared_url.replace("?dl=0", "?dl=1")
        if "dl=" not in direct:
            sep = "&" if "?" in direct else "?"
            direct = f"{direct}{sep}dl=1"
        return direct

    def _create_or_get_shared_link(self, path: str) -> str:
        """Create a public shared link, or return the existing one on conflict."""
        created = self._request(
            "POST",
            f"{_API_BASE}/sharing/create_shared_link_with_settings",
            json_body={
                "path": path,
                "settings": {
                    "requested_visibility": "public",
                    "audience": "public",
                    "access": "viewer",
                },
            },
        )
        if created.status_code == 200:
            body = created.json()
            url = body.get("url")
            if isinstance(url, str) and url:
                return url
        if created.status_code == 409:
            existing = self._list_shared_link_url(path)
            if existing:
                return existing
            raise DropboxError(f"No existing Dropbox shared link for {path!r}")
        try:
            created.raise_for_status()
        except httpx.HTTPError as exc:
            raise DropboxError(f"Dropbox shared link failed for {path!r}: {exc}") from exc
        raise DropboxError(f"Dropbox shared link missing url for {path!r}")

    def _list_shared_link_url(self, path: str) -> str | None:
        """Return an existing shared-link URL for ``path``, or None if missing."""
        listed = self._request(
            "POST",
            f"{_API_BASE}/sharing/list_shared_links",
            json_body={"path": path, "direct_only": True},
        )
        if listed.status_code == 409:
            # path not found / not shared
            return None
        try:
            listed.raise_for_status()
        except httpx.HTTPError as exc:
            raise DropboxError(f"Dropbox list_shared_links failed for {path!r}: {exc}") from exc
        links: list[dict[str, Any]] = listed.json().get("links") or []
        for link in links:
            url = link.get("url")
            if isinstance(url, str) and url:
                return url
        return None

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
        _retried: bool = False,
    ) -> httpx.Response:
        """Authenticated Dropbox call; refresh once on expired access token."""
        token = self._get_access_token()
        req_headers = {"Authorization": f"Bearer {token}"}
        if headers:
            req_headers.update(headers)
        try:
            response = self._http.request(
                method,
                url,
                headers=req_headers,
                json=json_body,
                content=content,
            )
        except httpx.HTTPError as exc:
            raise DropboxError(f"Dropbox request failed for {url!r}: {exc}") from exc

        if response.status_code == 401 and not _retried:
            logger.info("Dropbox access token rejected; refreshing and retrying once")
            self._invalidate_access_token()
            return self._request(
                method,
                url,
                headers=headers,
                json_body=json_body,
                content=content,
                _retried=True,
            )
        return response

    def _get_access_token(self) -> str:
        with self._token_lock:
            now = time.monotonic()
            if self._access_token and now < self._access_token_expires_at - _EXPIRY_SKEW_SECONDS:
                return self._access_token
            return self._refresh_access_token_locked()

    def _invalidate_access_token(self) -> None:
        with self._token_lock:
            self._access_token = None
            self._access_token_expires_at = 0.0

    def _refresh_access_token_locked(self) -> str:
        """Exchange refresh_token for a short-lived access token. Caller holds lock."""
        try:
            response = self._http.post(
                _TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": self._app_key,
                    "client_secret": self._app_secret,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DropboxError(f"Dropbox token refresh failed: {exc}") from exc

        body = response.json()
        access_token = body.get("access_token")
        expires_in = body.get("expires_in")
        if not isinstance(access_token, str) or not access_token:
            raise DropboxError("Dropbox token refresh returned no access_token")
        if not isinstance(expires_in, int | float) or expires_in <= 0:
            # Dropbox normally returns ~14400; fall back so we still refresh soon.
            expires_in = 14400
            logger.warning(
                "Dropbox token refresh missing expires_in; assuming %s seconds",
                expires_in,
            )

        self._access_token = access_token
        self._access_token_expires_at = time.monotonic() + float(expires_in)
        logger.debug("Dropbox access token refreshed; expires_in=%s", expires_in)
        return access_token
