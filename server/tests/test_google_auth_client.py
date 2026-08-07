"""Certificate caching in the Google ID token verifier.

Token verification re-fetches Google's signing certificates on every call unless
something caches them, which put an outbound round-trip to Google on the hot path
of every authenticated request. These cover the cache that removes it.
"""

import core.clients.google_auth as google_auth_module
from core.clients.google_auth import _CachingRequest


class _FakeResponse:
    def __init__(self, status: int = 200, data: bytes = b"{}") -> None:
        self.status = status
        self.data = data


class _RecordingTransport:
    """Stands in for the real google-auth transport, counting calls."""

    def __init__(self, response: _FakeResponse | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._response = response or _FakeResponse()

    def __call__(self, url: str, method: str = "GET", **_: object) -> _FakeResponse:
        self.calls.append((url, method))
        return self._response


def _caching_request(transport: _RecordingTransport, ttl_seconds: int = 3600) -> _CachingRequest:
    request = _CachingRequest(ttl_seconds=ttl_seconds)
    request._inner = transport
    return request


CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"


def test_repeated_gets_hit_the_network_once():
    transport = _RecordingTransport()
    request = _caching_request(transport)

    for _ in range(5):
        request(CERTS_URL)

    assert len(transport.calls) == 1


def test_cached_response_is_returned_intact():
    transport = _RecordingTransport(_FakeResponse(data=b'{"kid": "cert"}'))
    request = _caching_request(transport)

    first = request(CERTS_URL)
    second = request(CERTS_URL)

    # google-auth decodes `.data` on every verification, so a cached response
    # has to stay readable rather than being a spent stream.
    assert first.data == second.data == b'{"kid": "cert"}'


def test_expired_entries_are_refetched():
    transport = _RecordingTransport()
    request = _caching_request(transport, ttl_seconds=0)

    request(CERTS_URL)
    request(CERTS_URL)

    assert len(transport.calls) == 2


def test_failures_are_not_cached():
    transport = _RecordingTransport(_FakeResponse(status=503))
    request = _caching_request(transport)

    request(CERTS_URL)
    request(CERTS_URL)

    # Pinning a transient failure for the full TTL would turn a momentary Google
    # blip into an hour of rejected logins.
    assert len(transport.calls) == 2


def test_non_get_requests_bypass_the_cache():
    transport = _RecordingTransport()
    request = _caching_request(transport)

    request(CERTS_URL, method="POST")
    request(CERTS_URL, method="POST")

    assert len(transport.calls) == 2


def test_verify_id_token_passes_clock_skew(monkeypatch):
    """A marginally fast server clock must not reject a still-valid token."""
    captured: dict[str, object] = {}

    def fake_verify(token, request, audience=None, clock_skew_in_seconds=0):
        captured["clock_skew_in_seconds"] = clock_skew_in_seconds
        captured["audience"] = audience
        return {"sub": "123"}

    monkeypatch.setattr(google_auth_module.id_token, "verify_oauth2_token", fake_verify)

    client = google_auth_module.GoogleAuthClient("test-client-id")
    assert client.verify_id_token("a.b.c") == {"sub": "123"}
    assert captured["clock_skew_in_seconds"] > 0
    assert captured["audience"] == "test-client-id"
