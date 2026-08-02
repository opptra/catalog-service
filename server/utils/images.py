"""Generic image helpers — fetch a remote image and inline it as a data URL."""

import base64

import httpx


def to_data_url(url: str, *, timeout: float = 15.0) -> str | None:
    """Fetch ``url`` and return a ``data:`` URL, or ``None`` if it isn't a reachable image.

    Inlining as base64 makes the reference image portable across providers instead of relying
    on the model host being able to fetch a remote URL.
    """
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
    if not content_type.startswith("image/"):
        return None

    encoded = base64.b64encode(response.content).decode("ascii")
    return f"data:{content_type};base64,{encoded}"
