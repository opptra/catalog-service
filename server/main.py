from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.clients.db import DatabaseClient
from core.config import settings
from routers import health, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    catalog_db = DatabaseClient(settings.catalog_database_url)
    user_db = DatabaseClient(settings.user_database_url)
    app.state.catalog_db = catalog_db
    app.state.user_db = user_db
    try:
        yield
    finally:
        catalog_db.close()
        user_db.close()


app = FastAPI(title="Catalog Service", lifespan=lifespan)

app.include_router(health.router)
app.include_router(users.router)
