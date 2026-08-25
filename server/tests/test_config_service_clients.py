from core.config import Settings

_REQUIRED_KWARGS = {
    "db_host": "localhost",
    "db_name": "db",
    "db_user": "user",
    "db_password": "pw",
    "user_service_db_name": "user_db",
    "google_client_id": "client-id",
    "openrouter_text_model": "m",
    "openrouter_image_model": "m",
    "openrouter_verify_model": "m",
}


def test_flat_service_client_env_vars_are_collected(monkeypatch):
    monkeypatch.setenv("SERVICE_CLIENT_CATALOG_WORKFLOWS", "shared-token")
    settings = Settings(**_REQUIRED_KWARGS)
    assert settings.service_clients == {"catalog-workflows": "shared-token"}


def test_multiple_service_clients_are_all_collected(monkeypatch):
    monkeypatch.setenv("SERVICE_CLIENT_CATALOG_WORKFLOWS", "tok-a")
    monkeypatch.setenv("SERVICE_CLIENT_ANOTHER_CALLER", "tok-b")
    settings = Settings(**_REQUIRED_KWARGS)
    assert settings.service_clients == {
        "catalog-workflows": "tok-a",
        "another-caller": "tok-b",
    }


def test_no_service_client_env_vars_yields_empty_map(monkeypatch):
    import os

    for key in list(os.environ):
        if key.startswith("SERVICE_CLIENT_"):
            monkeypatch.delenv(key, raising=False)
    settings = Settings(**_REQUIRED_KWARGS)
    assert settings.service_clients == {}
