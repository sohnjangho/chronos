from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.chat import service
from app.programs.chat.schemas import (
    ChatSessionDetail,
    ChatSessionIn,
    ChatSessionItem,
    ChatSessionOut,
    MessageIn,
    StopOut,
)
from app.security.deps import current_user
from app.store.tables import User

# 대화는 만든 사용자만 본다.
router = APIRouter(prefix="/api/chat", tags=["chat"])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@router.get("/sessions")
def list_chat_sessions(session: SessionDep, user: UserDep) -> list[ChatSessionItem]:
    return service.list_sessions(session, user)


@router.post("/sessions")
def create_chat_session(session: SessionDep, user: UserDep, body: ChatSessionIn | None = None) -> ChatSessionOut:
    return service.create(session, user, body)


@router.get("/sessions/{chat_id}")
def read_chat_session(chat_id: int, session: SessionDep, user: UserDep) -> ChatSessionDetail:
    return service.detail(session, user, chat_id)


# async: 턴 맡기(claim)를 이벤트 루프 한 곳에서 해 두 요청이 같이 맡지 못하게 한다.
@router.post("/sessions/{chat_id}/messages", response_class=StreamingResponse)
async def post_message(chat_id: int, body: MessageIn, session: SessionDep, user: UserDep) -> StreamingResponse:
    return service.start_turn(session, user, chat_id, body)


@router.post("/sessions/{chat_id}/stop")
def stop_turn(chat_id: int, session: SessionDep, user: UserDep) -> StopOut:
    return service.stop(session, user, chat_id)
