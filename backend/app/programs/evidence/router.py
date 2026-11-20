from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.evidence import service
from app.programs.evidence.schemas import EvidenceOut
from app.security.deps import current_user
from app.store.tables import User

# 로그인한 누구나. 대화로 거르면 그 대화를 만든 사용자만(service 가 404).
router = APIRouter(prefix="/api/evidence", tags=["evidence"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@router.get("")
def list_evidence(
    session: SessionDep, user: UserDep, schedule_id: int | None = None, chat_session_id: int | None = None
) -> list[EvidenceOut]:
    return service.list_evidence(session, user, schedule_id, chat_session_id)
