import os
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

_SERVICE_CLIENT_ENV_PREFIX = "SERVICE_CLIENT_"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str

    user_service_db_name: str

    api_key: str | None = None

    google_client_id: str

    # Machine callers for @internal_api routes: { "catalog-workflows": "<token>", ... }.
    # Secret Manager stores these nested as server.SERVICE_CLIENTS; scripts flatten to
    # SERVICE_CLIENT_<ID> env vars. Settings collects those flat keys here (see
    # _collect_service_clients). Local .env uses the flat form for easy testing.
    service_clients: dict[str, str] = {}

    cors_origins: str = ""

    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Model IDs the generation pipeline passes to OpenRouter. The client never
    # hardcodes models — set these in .env. Swap openrouter_image_model among the
    # known comparison IDs (see .env.example) to pick gemini / gpt / grok path.
    openrouter_prompt_model: str
    openrouter_text_model: str
    openrouter_image_model: str

    # Google Cloud — used by GCS + Cloud Workflows clients (ADC for credentials).
    # Leave unset to disable those clients locally.
    google_cloud_project: str | None = None
    gcs_bucket: str | None = None
    workflows_location: str = "asia-south1"

    @model_validator(mode="before")
    @classmethod
    def _collect_service_clients(cls, data: object) -> object:
        """Build service_clients from flat SERVICE_CLIENT_<ID> env vars.

        Secret Manager uses nested SERVICE_CLIENTS; scripts flatten before the
        process starts. Client IDs are dynamic, so they can't be declared fields —
        this reads os.environ directly.
        SERVICE_CLIENT_CATALOG_WORKFLOWS=<token> -> {"catalog-workflows": "<token>"}.
        """
        if not isinstance(data, dict):
            return data
        clients = {}
        for key, value in os.environ.items():
            if not key.startswith(_SERVICE_CLIENT_ENV_PREFIX) or not value:
                continue
            client_id = key[len(_SERVICE_CLIENT_ENV_PREFIX) :].lower().replace("_", "-")
            clients[client_id] = value
        data["service_clients"] = clients
        return data

    def _build_url(self, db_name: str) -> str:
        user = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        # Cloud SQL Unix socket: DB_HOST=/cloudsql/PROJECT:REGION:INSTANCE
        if self.db_host.startswith("/"):
            return f"postgresql+psycopg://{user}:{password}@/{db_name}?host={self.db_host}"
        return f"postgresql+psycopg://{user}:{password}@{self.db_host}:{self.db_port}/{db_name}"

    @property
    def catalog_database_url(self) -> str:
        return self._build_url(self.db_name)

    @property
    def user_database_url(self) -> str:
        return self._build_url(self.user_service_db_name)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
