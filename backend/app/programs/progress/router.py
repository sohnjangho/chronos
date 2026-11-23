from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.progress import field, service
from app.programs.progress.field import (
    CreatePollIn,
    DispatchCheckinIn,
    FieldListOut,
    HandoffUpdateIn,
    PhotoUploadIn,
    RespondIn,
)
from app.programs.progress.schemas import ProgressOut, Unit
from app.security.deps import current_user
from app.store.tables import User

# 로그인한 사람은 누구나 읽고 현장 회신을 남긴다.
router = APIRouter(prefix="/api/schedules", tags=["progress"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@router.get("/{schedule_id}/progress")
def read_progress(schedule_id: int, session: SessionDep, unit: Unit = "week") -> ProgressOut:
    return service.progress(session, schedule_id, unit)


@router.get("/{schedule_id}/field")
def read_field(schedule_id: int, session: SessionDep) -> FieldListOut:
    return field.list_field(session, schedule_id)


@router.post("/{schedule_id}/field/checkins/dispatch")
def dispatch_checkins(schedule_id: int, body: DispatchCheckinIn, session: SessionDep) -> FieldListOut:
    return field.dispatch_checkins(session, schedule_id, body)


@router.post("/{schedule_id}/field/photos")
async def upload_field_photo(schedule_id: int, body: PhotoUploadIn, session: SessionDep) -> FieldListOut:
    return await field.upload_photo(session, schedule_id, body)


@router.post("/{schedule_id}/field/polls")
def create_field_poll(schedule_id: int, body: CreatePollIn, session: SessionDep) -> FieldListOut:
    return field.create_poll(session, schedule_id, body)


@router.post("/{schedule_id}/field/{item_id}/respond")
def respond_field_item(schedule_id: int, item_id: int, body: RespondIn, session: SessionDep) -> FieldListOut:
    return field.respond_item(session, schedule_id, item_id, body)


@router.post("/{schedule_id}/field/{item_id}/handoff")
def update_field_handoff(schedule_id: int, item_id: int, body: HandoffUpdateIn, session: SessionDep) -> FieldListOut:
    return field.update_handoff(session, schedule_id, item_id, body)


@router.post("/{schedule_id}/field/{item_id}/apply")
def apply_field_item(schedule_id: int, item_id: int, session: SessionDep, user: UserDep) -> FieldListOut:
    return field.apply_item(session, schedule_id, item_id, user)
