from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class DatabaseClient:
    """Engine + session factory. Queries belong in repositories via the ORM."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
        )

    def close(self) -> None:
        self.engine.dispose()
