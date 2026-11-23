from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.schedule import service
from app.programs.schedule.schemas import (
    ActivityCreate,
    ActivityPatch,
    PredecessorsIn,
    RestoreIn,
    ScheduleCreate,
    ScheduleItem,
    SchedulePatch,
    ScheduleView,
    VersionOut,
    WeightModeIO,
)
from app.security.deps import current_user, require_editor
from app.store.tables import User

# 로그인한 사람은 누구나 읽는다. 고치기·되돌리기·새 일정은 현장 관리자를 뺀 사람만(F4).
router = APIRouter(
    prefix="/api/schedules", tags=["schedules"], dependencies=[Depends(current_user)]
)

SessionDep = Annotated[Session, Depends(get_session)]
EditorDep = Annotated[User, Depends(require_editor)]


@router.get("")
def list_schedules(session: SessionDep) -> list[ScheduleItem]:
    return service.list_schedules(session)


@router.post("", status_code=201)
def create_schedule_project(body: ScheduleCreate, session: SessionDep, user: EditorDep) -> ScheduleItem:
    return service.create_project(session, body, user)


@router.get("/{schedule_id}")
def get_schedule(schedule_id: int, session: SessionDep) -> ScheduleView:
    return service.get_view(session, schedule_id)


@router.patch("/{schedule_id}")
def patch_schedule(schedule_id: int, body: SchedulePatch, session: SessionDep, user: EditorDep) -> ScheduleView:
    return service.patch_schedule(session, schedule_id, body, user)


@router.put("/{schedule_id}/weight-mode")
def set_weight_mode(schedule_id: int, body: WeightModeIO, session: SessionDep) -> WeightModeIO:
    return service.set_weight_mode(session, schedule_id, body)


@router.patch("/{schedule_id}/activities/{aid}")
def patch_activity(
    schedule_id: int, aid: str, body: ActivityPatch, session: SessionDep, user: EditorDep
) -> ScheduleView:
    return service.patch_activity(session, schedule_id, aid, body, user)


@router.post("/{schedule_id}/activities")
def add_activity(
    schedule_id: int, body: ActivityCreate, session: SessionDep, user: EditorDep
) -> ScheduleView:
    return service.add_activity(session, schedule_id, body, user)


@router.delete("/{schedule_id}/activities/{aid}")
def delete_activity(
    schedule_id: int, aid: str, base_version: int, session: SessionDep, user: EditorDep
) -> ScheduleView:
    return service.delete_activity(session, schedule_id, aid, base_version, user)


@router.put("/{schedule_id}/activities/{aid}/predecessors")
def set_predecessors(
    schedule_id: int, aid: str, body: PredecessorsIn, session: SessionDep, user: EditorDep
) -> ScheduleView:
    return service.set_predecessors(session, schedule_id, aid, body, user)


@router.get("/{schedule_id}/versions")
def list_versions(schedule_id: int, session: SessionDep) -> list[VersionOut]:
    return service.versions(session, schedule_id)


@router.post("/{schedule_id}/versions/{n}/restore")
def restore_version(
    schedule_id: int, n: int, body: RestoreIn, session: SessionDep, user: EditorDep
) -> ScheduleView:
    return service.restore_version(session, schedule_id, n, body.base_version, user)
