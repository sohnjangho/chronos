from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, validate_settings
from app.db import close_db, init_db
from app.errors import install_error_handlers
from app.programs.auth.router import router as auth_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_settings(Settings())
    init_db()
    yield
    close_db()


app = FastAPI(title="ChronOS", lifespan=lifespan)
install_error_handlers(app)
app.include_router(auth_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
