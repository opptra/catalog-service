from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import Settings


class DatabaseClient:
    """Engine + session factory. Queries belong in repositories via the ORM."""

    def __init__(self, settings: Settings) -> None:
        self.engine = create_engine(settings.database_url, pool_pre_ping=True)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
        )

    def close(self) -> None:
        self.engine.dispose()
