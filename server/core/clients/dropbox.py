"""Dropbox client — upload bytes and return a durable public HTTPS URL."""

from __future__ import annotations

import json
import logging
import threading
import time
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
    """

    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        refresh_token: str,
        root_path: str = "/catalog-service/listing-images",
        timeout: float = 120.0,
    ) -> None:
        if not app_key or not app_secret or not refresh_token:
            raise ValueError("Dropbox app_key, app_secret, and refresh_token are required")
        self._app_key = app_key
        self._app_secret = app_secret
        self._refresh_token = refresh_token
        self._root_path = root_path.rstrip("/") or "/catalog-service/listing-images"
        self._http = httpx.Client(timeout=timeout)
        self._token_lock = threading.Lock()
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0

    def close(self) -> None:
        self._http.close()

    def upload_bytes(
        self,
        data: bytes,
        relative_path: str,
    ) -> DropboxUploadedObject:
        """Upload ``data`` and return a durable shared HTTPS URL (``dl=1``)."""
        if not relative_path:
            raise ValueError("relative_path is required")
        path = f"{self._root_path}/{relative_path.lstrip('/')}"
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

        shared_url = self._ensure_shared_url(path)
        # Prefer a direct-download form Amazon can fetch without a preview page.
        direct = shared_url.replace("?dl=0", "?dl=1")
        if "dl=" not in direct:
            sep = "&" if "?" in direct else "?"
            direct = f"{direct}{sep}dl=1"
        return DropboxUploadedObject(path=path, shared_url=direct)

    def _ensure_shared_url(self, path: str) -> str:
        """Create or reuse a public shared link for ``path``."""
        try:
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
            # already_exists → list existing links
            if created.status_code == 409:
                return self._existing_shared_url(path)
            created.raise_for_status()
        except httpx.HTTPError as exc:
            raise DropboxError(f"Dropbox shared link failed for {path!r}: {exc}") from exc
        raise DropboxError(f"Dropbox shared link missing url for {path!r}")

    def _existing_shared_url(self, path: str) -> str:
        try:
            listed = self._request(
                "POST",
                f"{_API_BASE}/sharing/list_shared_links",
                json_body={"path": path, "direct_only": True},
            )
            listed.raise_for_status()
            links: list[dict[str, Any]] = listed.json().get("links") or []
        except httpx.HTTPError as exc:
            raise DropboxError(f"Dropbox list_shared_links failed for {path!r}: {exc}") from exc
        for link in links:
            url = link.get("url")
            if isinstance(url, str) and url:
                return url
        raise DropboxError(f"No existing Dropbox shared link for {path!r}")

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
