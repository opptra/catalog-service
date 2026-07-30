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

    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    generate_input_dir: str = "data/generate-pipeline/v1"
    generate_output_dir: str = "storage/generated"
    openrouter_text_model: str = "openai/gpt-4o-mini"
    openrouter_image_model: str = "openai/gpt-5-image"

    @property
    def database_url(self) -> str:
        user = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        # Cloud SQL Unix socket: DB_HOST=/cloudsql/PROJECT:REGION:INSTANCE
        if self.db_host.startswith("/"):
            return f"postgresql+psycopg://{user}:{password}@/{self.db_name}?host={self.db_host}"
        return (
            f"postgresql+psycopg://{user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
