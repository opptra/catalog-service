import threading
import time
from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

# Google rotates its signing certificates infrequently and serves them with a
# long max-age. Cache them in-process so verifying a token is a local signature
# check rather than an outbound round-trip to Google on every request.
_CERTS_TTL_SECONDS = 3600

# Tolerate small clock differences between us and Google so a token that is
# still valid isn't rejected by a marginally fast server clock.
_CLOCK_SKEW_SECONDS = 10


class _CachingRequest:
    """A google-auth transport that memoises GET responses for a TTL.

    ``id_token.verify_oauth2_token`` re-fetches Google's signing certificates on
    every single call — google-auth ships no cache of its own and its docs point
    at ``CacheControl`` to add one. This is that cache without the extra
    dependency; certificate fetches are the only GET verification performs.

    Responses are safe to hand out repeatedly: the transport's ``data`` property
    returns ``requests``' already-buffered ``content`` bytes, not a live stream.
    """

    def __init__(self, ttl_seconds: int = _CERTS_TTL_SECONDS) -> None:
        self._inner = google_requests.Request()
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, Any]] = {}

    def __call__(self, url: str, method: str = "GET", **kwargs: Any) -> Any:
        if method != "GET":
            return self._inner(url, method=method, **kwargs)

        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(url)
            if entry is not None and entry[0] > now:
                return entry[1]

        response = self._inner(url, method=method, **kwargs)

        # Only cache success. Pinning a transient 5xx for an hour would turn a
        # momentary Google blip into an hour of failed logins.
        if getattr(response, "status", None) == 200:
            with self._lock:
                self._cache[url] = (now + self._ttl, response)

        return response


class GoogleAuthClient:
    """Verifies Google ID tokens against a configured OAuth client ID."""

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self._request = _CachingRequest()

    def verify_id_token(self, token: str) -> dict[str, Any]:
        return id_token.verify_oauth2_token(
            token,
            self._request,
            self.client_id,
            clock_skew_in_seconds=_CLOCK_SKEW_SECONDS,
        )
