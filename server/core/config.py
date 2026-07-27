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
    api_key: str | None = None

    @property
    def database_url(self) -> str:
        user = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        # Cloud SQL Unix socket: DB_HOST=/cloudsql/PROJECT:REGION:INSTANCE
        if self.db_host.startswith("/"):
            return (
                f"postgresql+psycopg://{user}:{password}@/{self.db_name}"
                f"?host={self.db_host}"
            )
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
