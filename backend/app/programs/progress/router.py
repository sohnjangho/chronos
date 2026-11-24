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
    HumanReadIn,
    PhotoUploadIn,
    RespondIn,
    RetakeIn,
)
from app.programs.progress.schemas import ProgressOut, Unit
from app.security.deps import current_user
from app.store.settings import can_human_read
from app.store.tables import User

# 로그인한 사람은 누구나 읽고 현장 회신을 남긴다.
router = APIRouter(prefix="/api/schedules", tags=["progress"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


def _for(session: Session, user: User, out: FieldListOut) -> FieldListOut:
    """현장 허브 응답에 이 사람이 사진 사람 판독을 할 수 있는지 붙인다(화면이 대기 목록·입력 칸을 그릴지 정한다)."""
    out.can_human_read = can_human_read(session, user.role)
    return out


@router.get("/{schedule_id}/progress")
def read_progress(schedule_id: int, session: SessionDep, unit: Unit = "week") -> ProgressOut:
    return service.progress(session, schedule_id, unit)


@router.get("/{schedule_id}/field")
def read_field(schedule_id: int, session: SessionDep, user: UserDep) -> FieldListOut:
    return _for(session, user, field.list_field(session, schedule_id))


@router.post("/{schedule_id}/field/checkins/dispatch")
def dispatch_checkins(schedule_id: int, body: DispatchCheckinIn, session: SessionDep, user: UserDep) -> FieldListOut:
    return _for(session, user, field.dispatch_checkins(session, schedule_id, body))


@router.post("/{schedule_id}/field/photos")
async def upload_field_photo(schedule_id: int, body: PhotoUploadIn, session: SessionDep, user: UserDep) -> FieldListOut:
    return _for(session, user, await field.upload_photo(session, schedule_id, body, user))


@router.post("/{schedule_id}/field/polls")
def create_field_poll(schedule_id: int, body: CreatePollIn, session: SessionDep, user: UserDep) -> FieldListOut:
    return _for(session, user, field.create_poll(session, schedule_id, body))


@router.post("/{schedule_id}/field/{item_id}/respond")
def respond_field_item(schedule_id: int, item_id: int, body: RespondIn, session: SessionDep, user: UserDep) -> FieldListOut:
    return _for(session, user, field.respond_item(session, schedule_id, item_id, body))


@router.post("/{schedule_id}/field/{item_id}/handoff")
def update_field_handoff(schedule_id: int, item_id: int, body: HandoffUpdateIn, session: SessionDep,
                         user: UserDep) -> FieldListOut:
    return _for(session, user, field.update_handoff(session, schedule_id, item_id, body))


@router.post("/{schedule_id}/field/{item_id}/apply")
def apply_field_item(schedule_id: int, item_id: int, session: SessionDep, user: UserDep) -> FieldListOut:
    return _for(session, user, field.apply_item(session, schedule_id, item_id, user))


@router.post("/{schedule_id}/field/{item_id}/human-read")
def human_read_field_photo(schedule_id: int, item_id: int, body: HumanReadIn, session: SessionDep, user: UserDep) -> FieldListOut:
    return _for(session, user, field.human_read(session, schedule_id, item_id, body, user))


@router.post("/{schedule_id}/field/{item_id}/retake")
def ask_field_photo_retake(schedule_id: int, item_id: int, body: RetakeIn, session: SessionDep, user: UserDep) -> FieldListOut:
    return _for(session, user, field.retake(session, schedule_id, item_id, body, user))
