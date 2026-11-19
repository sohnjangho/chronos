from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, validate_settings
from app.db import close_db, init_db
from app.errors import install_error_handlers
from app.programs.auth.router import router as auth_router
from app.programs.chat.router import router as chat_router
from app.programs.llm_settings.router import router as llm_settings_router
from app.programs.questionnaire.router import router as questionnaire_router
from app.programs.schedule.router import router as schedule_router
from app.programs.workflow.router import router as workflow_router
from app.tools import registry


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_settings(Settings())
    init_db()
    registry.load_all()  # 에이전트가 쓸 도구를 모두 등록한다
    yield
    close_db()


app = FastAPI(title="ChronOS", lifespan=lifespan)
install_error_handlers(app)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(llm_settings_router)
app.include_router(questionnaire_router)
app.include_router(schedule_router)
app.include_router(workflow_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
