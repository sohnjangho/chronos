from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.visuals import service
from app.programs.visuals.schemas import VisualIn, VisualOut
from app.security.deps import current_user
from app.store.tables import User

# 보고서용 그림: 로그인한 누구나 만들고 본다. 일정은 바뀌지 않는다.
router = APIRouter(prefix="/api/schedules", tags=["visuals"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@router.post("/{schedule_id}/visuals")
async def make_visual(schedule_id: int, body: VisualIn, session: SessionDep, user: UserDep) -> VisualOut:
    return await service.make(session, schedule_id, body, user)


@router.get("/{schedule_id}/visuals/{visual_id}")
def read_visual(schedule_id: int, visual_id: int, session: SessionDep) -> VisualOut:
    return service.read(session, schedule_id, visual_id)
