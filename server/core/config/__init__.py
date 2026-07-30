from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


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

    cors_origins: str = ""

    # Paths the auth middleware serves without a Google ID token.
    public_paths: list[str] = [
        "/",
        "/health",
        "/auth/google",
        "/docs",
        "/redoc",
        "/openapi.json",
    ]

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
