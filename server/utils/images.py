"""Fetch a remote image and inline it as a ``data:`` URL for chat-vision calls."""

import base64

import httpx


def bytes_to_data_url(content: bytes, content_type: str) -> str:
    """Encode in-memory image bytes as a ``data:`` URL."""
    if not content:
        raise ValueError("image content is empty")
    media = (content_type or "").split(";", 1)[0].strip() or "image/png"
    if not media.startswith("image/"):
        media = "image/png"
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{media};base64,{encoded}"


def to_data_url(url: str, *, timeout: float = 15.0) -> str | None:
    """Turn an image URL into a ``data:`` URL, or ``None`` if it cannot be inlined.

    Already-inlined ``data:`` URLs pass through. Remote URLs are fetched here so a
    chat-completions host never has to GET a signed GCS link itself.
    """
    text = url.strip()
    if not text:
        return None
    if text.startswith("data:"):
        return text
    try:
        response = httpx.get(text, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
    if not content_type.startswith("image/"):
        return None
    return bytes_to_data_url(response.content, content_type)


def to_data_urls(urls: list[str], *, timeout: float = 15.0) -> list[str]:
    """Inline each URL; skip any that cannot be fetched."""
    out: list[str] = []
    for url in urls:
        inlined = to_data_url(url, timeout=timeout)
        if inlined:
            out.append(inlined)
    return out
