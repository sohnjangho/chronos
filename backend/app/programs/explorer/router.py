from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.explorer import service
from app.programs.explorer.schemas import DeletedOut, TreeOut
from app.security.deps import current_user, require_admin
from app.store.tables import User

# 로그인한 누구나 일정 목록을 본다. 일정 지우기는 관리자만(일정 프로그램이 아니라 여기에 둔다).
router = APIRouter(tags=["explorer"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
AdminDep = Annotated[User, Depends(require_admin)]


@router.get("/api/explorer/tree")
def read_tree(session: SessionDep) -> TreeOut:
    return service.tree(session)


@router.delete("/api/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, session: SessionDep, admin: AdminDep) -> DeletedOut:
    return service.delete_schedule(session, schedule_id, admin)
