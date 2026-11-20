from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.attention import service
from app.programs.attention.schemas import AttentionOut
from app.security.deps import current_user

# 바탕화면 「주의할 일정」 위젯이 읽는다: 로그인한 누구나 본다(일정 목록과 같은 범위).
router = APIRouter(prefix="/api/attention", tags=["attention"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("")
def list_attention(session: SessionDep) -> AttentionOut:
    return service.attention(session)
