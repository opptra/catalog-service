from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.clients.db import DatabaseClient
from core.config import settings
from routers import health, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = DatabaseClient(settings)
    app.state.db = db
    try:
        yield
    finally:
        db.close()


app = FastAPI(title="Catalog Service", lifespan=lifespan)

app.include_router(health.router)
app.include_router(users.router)
