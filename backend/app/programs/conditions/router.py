from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.conditions import service
from app.programs.conditions.schemas import (
    AskOut,
    ChangesIn,
    CommitOut,
    ConditionsOut,
    PreviewOut,
)
from app.security.deps import current_user, require_editor
from app.store.tables import User

# 로그인한 누구나 보고 바꿔 본다. 분야 규칙 켜고 끄기만 관리자(service 가 403).
router = APIRouter(prefix="/api/schedules", tags=["conditions"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@router.get("/{schedule_id}/conditions")
def read_conditions(schedule_id: int, session: SessionDep, user: UserDep) -> ConditionsOut:
    return service.get_conditions(session, schedule_id, user)


@router.post("/{schedule_id}/conditions/preview")
def preview(schedule_id: int, body: ChangesIn, session: SessionDep, user: UserDep) -> PreviewOut:
    return service.preview(session, schedule_id, body, user)


@router.post("/{schedule_id}/conditions/commit")
def commit(
    schedule_id: int, body: ChangesIn, session: SessionDep, user: Annotated[User, Depends(require_editor)]
) -> CommitOut:
    return service.commit(session, schedule_id, body, user)


@router.post("/{schedule_id}/conditions/ask-agent")
def ask_agent(schedule_id: int, body: ChangesIn, session: SessionDep, user: UserDep) -> AskOut:
    return service.ask_agent(session, schedule_id, body, user)
