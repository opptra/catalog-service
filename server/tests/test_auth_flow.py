import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt

from core.auth.cookies import SESSION_COOKIE_NAME
from core.config import settings
from main import app
from services import session_jwt

_PATH_PARAM_RE = re.compile(r"\{[^}]+\}")
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# Routes annotated @no_auth — the only ones allowed to skip credentials.
_PUBLIC_PATHS = {"/api/", "/api/health", "/api/auth/google", "/api/auth/logout"}

_ISS = "catalog-service"
_AUD = "catalog-service"


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


def _fake_user(*, external_id=None):
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=1,
        external_id=external_id or uuid4(),
        email="tester@opptra.com",
        name="Tester",
        created_at=now,
        updated_at=now,
    )


def _mint_cookie(
    *,
    sub: str | None = None,
    exp_delta: timedelta | None = None,
    secret: str | None = None,
    aud: str = _AUD,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": sub or str(uuid4()),
        "iat": now,
        "exp": now + (exp_delta if exp_delta is not None else timedelta(hours=24)),
        "iss": _ISS,
        "aud": aud,
    }
    return jwt.encode(payload, secret or settings.session_jwt_secret, algorithm="HS256")


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
    assert client.post("/api/auth/logout").status_code == 204


def test_internal_route_missing_headers_is_rejected(client):
    response = client.post("/api/jobs/sku/test-id/execute/internal")
    assert response.status_code == 401


def test_internal_route_wrong_token_is_rejected(client, monkeypatch):
    from core.config import settings as cfg

    monkeypatch.setitem(cfg.service_clients, "catalog-workflows", "correct-token")
    response = client.post(
        "/api/jobs/sku/test-id/execute/internal",
        headers={"client-id": "catalog-workflows", "client-token": "wrong-token"},
    )
    assert response.status_code == 401


def test_google_user_route_missing_cookie_is_rejected(client):
    response = client.get("/api/users/me")
    assert response.status_code == 401


def test_valid_session_cookie_binds_user(client, monkeypatch):
    user = _fake_user()
    monkeypatch.setattr(
        "core.auth.authenticators.user_service.get_user_by_external_id",
        lambda _session, _external_id: user,
    )
    token = session_jwt.encode(user_external_id=user.external_id)
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api")
    response = client.get("/api/users/me")
    assert response.status_code == 200
    assert response.json()["external_id"] == str(user.external_id)


def test_bad_signature_cookie_is_rejected(client):
    token = _mint_cookie(secret="wrong-secret-not-the-configured-one")
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api")
    response = client.get("/api/users/me")
    assert response.status_code == 401


def test_wrong_audience_cookie_is_rejected(client):
    token = _mint_cookie(aud="other-service")
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api")
    response = client.get("/api/users/me")
    assert response.status_code == 401


def test_expired_cookie_is_rejected(client):
    token = _mint_cookie(exp_delta=timedelta(hours=-1))
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api")
    response = client.get("/api/users/me")
    assert response.status_code == 401


def test_logout_clears_session_cookie(client):
    token = _mint_cookie()
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api")
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    set_cookie = response.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()


def test_jobs_list_missing_brand_header_is_400(client, monkeypatch):
    user = _fake_user()
    monkeypatch.setattr(
        "core.auth.authenticators.user_service.get_user_by_external_id",
        lambda _session, _external_id: user,
    )
    token = session_jwt.encode(user_external_id=user.external_id)
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api")
    response = client.get("/api/jobs")
    assert response.status_code == 400


def test_jobs_list_without_grant_is_403(client, monkeypatch):
    from core.exceptions import BrandAccessDeniedError

    user = _fake_user()
    brand_id = uuid4()
    monkeypatch.setattr(
        "core.auth.authenticators.user_service.get_user_by_external_id",
        lambda _session, _external_id: user,
    )
    monkeypatch.setattr(
        "services.authorization.assert_brand_access",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(BrandAccessDeniedError(str(brand_id))),
    )
    token = session_jwt.encode(user_external_id=user.external_id)
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api")
    response = client.get("/api/jobs", headers={"Brand-Id": str(brand_id)})
    assert response.status_code == 403


def test_jobs_list_with_grant_succeeds(client, monkeypatch):
    user = _fake_user()
    brand_id = uuid4()
    monkeypatch.setattr(
        "core.auth.authenticators.user_service.get_user_by_external_id",
        lambda _session, _external_id: user,
    )
    monkeypatch.setattr(
        "services.authorization.assert_brand_access",
        lambda *_args, **_kwargs: (SimpleNamespace(), SimpleNamespace()),
    )
    monkeypatch.setattr(
        "routers.job.job_service.list_jobs",
        lambda *_args, **_kwargs: {"items": []},
    )
    token = session_jwt.encode(user_external_id=user.external_id)
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api")
    response = client.get("/api/jobs", headers={"Brand-Id": str(brand_id)})
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_create_job_without_grant_is_403(client, monkeypatch):
    from core.exceptions import BrandAccessDeniedError

    user = _fake_user()
    brand_id = uuid4()
    monkeypatch.setattr(
        "core.auth.authenticators.user_service.get_user_by_external_id",
        lambda _session, _external_id: user,
    )
    monkeypatch.setattr(
        "services.authorization.assert_brand_access",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(BrandAccessDeniedError(str(brand_id))),
    )
    token = session_jwt.encode(user_external_id=user.external_id)
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api")
    response = client.post(
        "/api/jobs",
        headers={"Brand-Id": str(brand_id)},
        json={
            "sku_ids": ["SKU-1"],
            "marketplace_external_id": str(uuid4()),
            "attributes": [{"attribute_external_id": str(uuid4()), "quantity": 1}],
        },
    )
    assert response.status_code == 403


def test_job_status_without_grant_is_403(client, monkeypatch):
    from core.exceptions import BrandAccessDeniedError

    user = _fake_user()
    job_id = uuid4()
    monkeypatch.setattr(
        "core.auth.authenticators.user_service.get_user_by_external_id",
        lambda _session, _external_id: user,
    )
    monkeypatch.setattr(
        "services.authorization.assert_job_access",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(BrandAccessDeniedError("denied")),
    )
    token = session_jwt.encode(user_external_id=user.external_id)
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api")
    response = client.get(f"/api/jobs/{job_id}/status")
    assert response.status_code == 403


def test_listings_fill_without_grant_is_403(client, monkeypatch):
    from core.exceptions import BrandAccessDeniedError

    user = _fake_user()
    job_id = uuid4()
    monkeypatch.setattr(
        "core.auth.authenticators.user_service.get_user_by_external_id",
        lambda _session, _external_id: user,
    )
    monkeypatch.setattr(
        "services.authorization.assert_job_access",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(BrandAccessDeniedError("denied")),
    )
    token = session_jwt.encode(user_external_id=user.external_id)
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api")
    response = client.post("/api/listings/fill", json={"job_external_id": str(job_id)})
    assert response.status_code == 403


def test_internal_route_ignores_session_cookie(client, monkeypatch):
    """A valid browser cookie must not authenticate @internal_api routes."""
    user = _fake_user()
    monkeypatch.setattr(
        "core.auth.authenticators.user_service.get_user_by_external_id",
        lambda _session, _external_id: user,
    )
    token = session_jwt.encode(user_external_id=user.external_id)
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api")
    response = client.post("/api/jobs/sku/test-id/execute/internal")
    assert response.status_code == 401
