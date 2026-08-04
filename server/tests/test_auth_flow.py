import re

from main import app

_PATH_PARAM_RE = re.compile(r"\{[^}]+\}")
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# Routes annotated @no_auth — the only ones allowed to skip credentials.
_PUBLIC_PATHS = {"/api/", "/api/health", "/api/auth/google"}


def _concrete_path(path: str) -> str:
    return _PATH_PARAM_RE.sub("test-id", path)


def _declared_routes() -> list[tuple[str, str]]:
    schema = app.openapi()
    return [
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method.upper() in _HTTP_METHODS
    ]


def test_internal_routes_are_exposed_with_suffix():
    paths = {path for _, path in _declared_routes()}
    assert "/api/jobs/sku/{external_id}/execute/internal" in paths
    assert "/api/jobs/{external_id}/complete/internal" in paths
    # The un-suffixed internal paths must not exist.
    assert "/api/jobs/sku/{external_id}/execute" not in paths
    assert "/api/jobs/{external_id}/complete" not in paths


def test_every_non_public_route_rejects_missing_credentials(client):
    routes = _declared_routes()
    assert routes, "expected at least one declared route"
    for method, path in routes:
        if path in _PUBLIC_PATHS:
            continue
        response = client.request(method, _concrete_path(path))
        assert response.status_code == 401, (
            f"{method} {path} should require auth, got {response.status_code}"
        )


def test_public_routes_do_not_require_credentials(client):
    assert client.get("/api/").status_code != 401
    assert client.get("/api/health").status_code != 401
    # No body -> 422 validation error, but never 401 (auth is skipped entirely).
    assert client.post("/api/auth/google").status_code != 401


def test_internal_route_missing_headers_is_rejected(client):
    response = client.post("/api/jobs/sku/test-id/execute/internal")
    assert response.status_code == 401


def test_internal_route_wrong_token_is_rejected(client, monkeypatch):
    from core.config import settings

    monkeypatch.setitem(settings.service_clients, "catalog-workflows", "correct-token")
    response = client.post(
        "/api/jobs/sku/test-id/execute/internal",
        headers={"client-id": "catalog-workflows", "client-token": "wrong-token"},
    )
    assert response.status_code == 401


def test_google_user_route_missing_bearer_is_rejected(client):
    response = client.get("/api/users/me")
    assert response.status_code == 401
