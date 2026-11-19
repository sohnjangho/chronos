"""대화 화면: 대화 만들기·목록·읽기, 메시지 보내기(턴의 사건을 SSE 로 흘려보냄), 멈춤.

대화는 만든 사용자만 본다(다른 사람에게는 404). 한 대화에서는 턴이 하나만 돈다(돌고 있으면 409).
턴은 요청 세션이 아니라 스트림이 여는 세션으로 돈다(응답을 보내는 동안 이어지므로).
"""

import weakref
from collections.abc import AsyncIterator
from contextlib import aclosing, contextmanager

from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent import turns
from app.agent.context import UiContext
from app.agent.events import to_sse
from app.agent.loop import run_turn
from app.db import get_session
from app.errors import ApiError
from app.programs.chat.schemas import (
    ChatSessionDetail,
    ChatSessionIn,
    ChatSessionOut,
    MessageIn,
    MessageOut,
    StopOut,
)
from app.store import chats, questionnaires
from app.store.tables import ChatSession, User
from app.store.timeutil import as_utc

NOT_FOUND_MESSAGE = "대화를 찾을 수 없습니다."
INVALID_QUESTIONNAIRE_MESSAGE = "이 대화에서 제출한 질문지가 아닙니다."
RESUMED_QUESTIONNAIRE_MESSAGE = "이미 이어서 처리한 질문지입니다."
TURN_RUNNING_MESSAGE = "앞의 요청을 처리하는 중입니다."
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _owned(session: Session, user: User, chat_id: int) -> ChatSession:
    try:
        chat = chats.get_chat(session, chat_id)
    except chats.NotFound:
        chat = None
    if chat is None or chat.user_id != user.id:
        raise ApiError(404, "not_found", NOT_FOUND_MESSAGE)
    return chat


def _out(chat: ChatSession) -> ChatSessionOut:
    return ChatSessionOut(id=chat.id, title=chat.title, schedule_id=chat.schedule_id, created_at=as_utc(chat.created_at))


def create(session: Session, user: User, body: ChatSessionIn | None) -> ChatSessionOut:
    return _out(chats.create_chat(session, user_id=user.id, schedule_id=body.schedule_id if body else None))


def list_sessions(session: Session, user: User) -> list[ChatSessionOut]:
    return [_out(c) for c in chats.list_chats(session, user.id)]


def detail(session: Session, user: User, chat_id: int) -> ChatSessionDetail:
    chat = _owned(session, user, chat_id)
    messages = [
        MessageOut(id=m.id, role=m.role, content=m.content_json, created_at=as_utc(m.created_at))
        for m in chats.messages(session, chat_id)
    ]
    return ChatSessionDetail(**_out(chat).model_dump(), running=turns.is_running(chat_id), messages=messages)


def stop(session: Session, user: User, chat_id: int) -> StopOut:
    _owned(session, user, chat_id)
    return StopOut(stopping=turns.request_stop(chat_id))


def _check_questionnaire(session: Session, chat_id: int, qid: int) -> None:
    """제출됐고 이 대화의 것이며 아직 이어 가지 않은 질문지만 받는다."""
    try:
        record = questionnaires.get(session, qid)
    except questionnaires.NotFound:
        record = None
    if record is None or record.status != "submitted" or record.chat_session_id != chat_id:
        raise ApiError(422, "invalid_questionnaire", INVALID_QUESTIONNAIRE_MESSAGE)
    if chats.was_resumed(session, chat_id, qid):
        raise ApiError(422, "invalid_questionnaire", RESUMED_QUESTIONNAIRE_MESSAGE)


def start_turn(session: Session, user: User, chat_id: int, body: MessageIn) -> StreamingResponse:
    """확인(404 → 422 질문지 → 409) 뒤 턴을 맡고 SSE 응답을 돌려준다(기다리는 동안 `: ping` 주석 줄)."""
    _owned(session, user, chat_id)
    if body.questionnaire_id is not None:
        _check_questionnaire(session, chat_id, body.questionnaire_id)
    try:
        held = turns.claim(chat_id)
    except turns.TurnRunning:
        raise ApiError(409, "turn_running", TURN_RUNNING_MESSAGE) from None
    ui = UiContext(body.ui.program, body.ui.schedule_id, body.ui.selected_activity)
    stream = turn_stream(chat_id, user.id, body.text, ui, body.questionnaire_id, held)
    weakref.finalize(stream, turns.release, chat_id, held)  # 시작도 못 하고 버려진 응답도 턴을 놓게
    return StreamingResponse(stream, media_type="text/event-stream", headers=_SSE_HEADERS)


async def turn_stream(
    chat_id: int, user_id: int, text: str | None, ui: UiContext, questionnaire_id: int | None, held: turns.Claim
) -> AsyncIterator[str]:
    """턴의 사건을 SSE 글로. 스트림이 끝나거나 닫히면(연결 끊김) 턴을 놓는다."""
    try:
        with contextmanager(get_session)() as session:
            user = session.get(User, user_id)
            turn = run_turn(session, user, chat_id, text, ui, questionnaire_id=questionnaire_id)
            async with aclosing(turn) as events:
                async for event in events:
                    yield to_sse(event)
    finally:
        turns.release(chat_id, held)
