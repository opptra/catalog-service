import os

import pytest

# Allow importing service modules in unit tests without a local .env.
for _key, _value in {
    "DB_HOST": "127.0.0.1",
    "DB_NAME": "catalog_service",
    "DB_USER": "postgres",
    "DB_PASSWORD": "test",
    "USER_SERVICE_DB_NAME": "user_service",
    "GOOGLE_CLIENT_ID": "test.apps.googleusercontent.com",
    "OPENROUTER_PROMPT_MODEL": "openai/gpt-5.4-mini",
    "OPENROUTER_TEXT_MODEL": "openai/gpt-5.4-mini",
    "OPENROUTER_IMAGE_MODEL": "google/gemini-3-pro-image",
    "REGION": "asia-south1",
}.items():
    os.environ.setdefault(_key, _value)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as test_client:
        yield test_client
