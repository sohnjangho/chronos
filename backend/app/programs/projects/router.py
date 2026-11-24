from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.projects import service
from app.programs.projects.schemas import ProjectOut, ProjectPatch
from app.security.deps import current_user, require_editor
from app.store.tables import User

# 로그인한 사람은 누구나 읽는다(일정 목록과 같다). 고치기는 현장 관리자를 뺀 사람만(일정 고치기와 같은 require_editor).
router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
EditorDep = Annotated[User, Depends(require_editor)]


@router.get("")
def list_projects(session: SessionDep) -> list[ProjectOut]:
    return service.list_projects(session)


@router.get("/{schedule_id}")
def get_project(schedule_id: int, session: SessionDep) -> ProjectOut:
    return service.get_project(session, schedule_id)


@router.patch("/{schedule_id}")
def patch_project(schedule_id: int, body: ProjectPatch, session: SessionDep, user: EditorDep) -> ProjectOut:
    """보낸 칸만. 이름을 바꿔도 버전·주소록·연락 기록은 그대로(schedule_id 로 가리킨다)."""
    return service.patch_project(session, schedule_id, body, user)
