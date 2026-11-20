from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.progress import service
from app.programs.progress.schemas import ProgressOut, Unit
from app.security.deps import current_user

# 로그인한 사람은 누구나 읽는다.
router = APIRouter(prefix="/api/schedules", tags=["progress"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/{schedule_id}/progress")
def read_progress(schedule_id: int, session: SessionDep, unit: Unit = "week") -> ProgressOut:
    return service.progress(session, schedule_id, unit)
