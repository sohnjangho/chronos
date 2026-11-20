from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.delays import service
from app.programs.delays.schemas import (
    DelayIn,
    DelayPatch,
    DelaysOut,
    PreviewOut,
    ScenarioIn,
    ScenarioOut,
)
from app.security.deps import current_user
from app.store.tables import User

# 지연 기록: 로그인한 누구나 적고 고치고 본다. 일정에 넣는 것은 지연 반영안을 승인함에서 승인할 때뿐이다.
router = APIRouter(prefix="/api/schedules", tags=["delays"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@router.get("/{schedule_id}/delays")
def list_delays(schedule_id: int, session: SessionDep) -> DelaysOut:
    return service.list_delays(session, schedule_id)


@router.post("/{schedule_id}/delays")
def create_delay(schedule_id: int, body: DelayIn, session: SessionDep, user: UserDep) -> DelaysOut:
    return service.create(session, schedule_id, body, user)


@router.post("/{schedule_id}/delays/analyze")
def analyze_delays(schedule_id: int, session: SessionDep) -> DelaysOut:
    return service.analyze(session, schedule_id)


@router.post("/{schedule_id}/delays/scenario")
def delay_scenario(schedule_id: int, body: ScenarioIn, session: SessionDep, user: UserDep) -> ScenarioOut:
    return service.scenario(session, schedule_id, body, user)


@router.get("/{schedule_id}/delays/preview")
def preview_delays(schedule_id: int, session: SessionDep) -> PreviewOut:
    return service.preview(session, schedule_id)


@router.patch("/{schedule_id}/delays/{eid}")
def patch_delay(schedule_id: int, eid: int, body: DelayPatch, session: SessionDep) -> DelaysOut:
    return service.patch(session, schedule_id, eid, body)


@router.delete("/{schedule_id}/delays/{eid}")
def delete_delay(schedule_id: int, eid: int, session: SessionDep) -> DelaysOut:
    return service.delete(session, schedule_id, eid)
