from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.workflow import service
from app.programs.workflow.schemas import RunDetail, RunOut, SkillCreateIn, SkillOut
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


@router.get("/skills")
def list_skills(session: SessionDep, user: UserDep) -> list[SkillOut]:
    return service.list_skills(session, user)


@router.post("/runs/{run_id}/save-skill", status_code=201)
def save_skill(run_id: int, body: SkillCreateIn, session: SessionDep, user: UserDep) -> SkillOut:
    return service.save_skill(session, user, run_id, body)


@router.delete("/skills/{skill_id}", status_code=204)
def delete_skill(skill_id: int, session: SessionDep, user: UserDep) -> Response:
    service.delete_skill(session, user, skill_id)
    return Response(status_code=204)
