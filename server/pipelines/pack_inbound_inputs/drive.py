"""Download public Google Drive file ids as image bytes."""

from __future__ import annotations

import logging
import re
import time
from typing import Protocol

import httpx

from core.exceptions.pack_inbound_inputs import PackInboundInputsError

logger = logging.getLogger(__name__)

_FILE_ID = re.compile(r"/d/([a-zA-Z0-9_-]+)|[?&]id=([a-zA-Z0-9_-]+)")
_CONFIRM = re.compile(r"confirm=([0-9A-Za-z_-]+)")
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_TRANSIENT = ("timed out", "timeout", "connection reset", "connection aborted")
_DOWNLOAD_ATTEMPTS = 3


class DriveFileStore(Protocol):
    def download(self, file_id: str) -> bytes: ...


def drive_file_id(url: str) -> str | None:
    text = url.strip()
    if not text:
        return None
    match = _FILE_ID.search(text)
    if match is None:
        return None
    return match.group(1) or match.group(2)


def looks_like_image(content: bytes) -> bool:
    if len(content) < 12:
        return False
    if content[:3] == b"\xff\xd8\xff":
        return True
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if content[:6] in {b"GIF87a", b"GIF89a"}:
        return True
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return True
    if content[:4] in {b"II*\x00", b"MM\x00*"}:
        return True
    return content[:2] == b"BM"


def _confirm_token(response: httpx.Response) -> str | None:
    match = _CONFIRM.search(response.text or "")
    if match is not None:
        return match.group(1)
    for name, value in response.cookies.items():
        if name.startswith("download_warning"):
            return value
    return None


def _is_transient(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(token in text for token in _TRANSIENT)


def image_suffix(content: bytes) -> str:
    if content[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if content[:6] in {b"GIF87a", b"GIF89a"}:
        return ".gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    if content[:4] in {b"II*\x00", b"MM\x00*"}:
        return ".tif"
    if content[:2] == b"BM":
        return ".bmp"
    return ".jpg"


class HttpxDriveStore:
    """Public-link Drive downloads. Files must be shared with anyone with the link."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=180.0,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            )
        return self._client

    def download(self, file_id: str) -> bytes:
        last_error: PackInboundInputsError | None = None
        for attempt in range(_DOWNLOAD_ATTEMPTS):
            try:
                return self._download_once(file_id)
            except PackInboundInputsError as exc:
                if "not a public image" in str(exc) or not _is_transient(exc):
                    raise
                last_error = exc
                delay = 2**attempt
                logger.warning(
                    "retry %s/%s for %s in %ss: %s",
                    attempt + 1,
                    _DOWNLOAD_ATTEMPTS,
                    file_id,
                    delay,
                    exc,
                )
                time.sleep(delay)
        raise last_error or PackInboundInputsError(f"Drive download failed for {file_id}")

    def _download_once(self, file_id: str) -> bytes:
        client = self._http()
        url = f"https://drive.google.com/uc?export=download&confirm=t&id={file_id}"
        try:
            response = client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PackInboundInputsError(f"Drive download failed for {file_id}: {exc}") from exc
        if looks_like_image(response.content):
            return response.content
        token = _confirm_token(response)
        if token is None:
            raise PackInboundInputsError(
                f"Drive file {file_id} is not a public image (login wall or empty file)"
            )
        retry_url = f"https://drive.google.com/uc?export=download&confirm={token}&id={file_id}"
        try:
            retry = client.get(retry_url)
            retry.raise_for_status()
        except httpx.HTTPError as exc:
            raise PackInboundInputsError(f"Drive download failed for {file_id}: {exc}") from exc
        if not looks_like_image(retry.content):
            raise PackInboundInputsError(
                f"Drive file {file_id} is not a public image (login wall or empty file)"
            )
        return retry.content
