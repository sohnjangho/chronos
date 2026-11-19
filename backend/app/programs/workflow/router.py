from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.workflow import service
from app.programs.workflow.schemas import RunDetail, RunOut
from app.security.deps import current_user
from app.store.tables import User

# 일반 사용자는 자기 대화의 실행만, 관리자는 모두 본다.
router = APIRouter(prefix="/api/workflows", tags=["workflows"])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@router.get("/runs")
def list_runs(session: SessionDep, user: UserDep) -> list[RunOut]:
    return service.list_runs(session, user)


@router.get("/runs/{run_id}")
def get_run(run_id: int, session: SessionDep, user: UserDep) -> RunDetail:
    return service.get_run(session, user, run_id)
