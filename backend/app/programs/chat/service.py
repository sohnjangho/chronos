"""대화 화면: 대화 만들기·목록·읽기, 메시지 보내기(턴의 사건을 SSE 로 흘려보냄), 멈춤.

다른 사람이 '거부하고 다시 짜기' 로 결정한 승인 건은 대화 주인의 목록·상세에 pending_retries 로 보이고,
주인이 approval_id 로 메시지를 보내야 이어 간다(남의 이름으로 턴을 돌리지 않는다).

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
from app.llm import assignments
from app.llm.connections import normalize_models
from app.programs.chat.schemas import (
    ChatFileOut,
    ChatModelIn,
    ChatModelOut,
    ChatSessionDetail,
    ChatSessionIn,
    ChatSessionItem,
    ChatSessionOut,
    MessageIn,
    MessageOut,
    RetryOut,
    StopOut,
)
from app.store import approvals, chats, questionnaires
from app.store import files as file_store
from app.store.tables import ChatSession, FileRow, LlmConnection, User
from app.store.timeutil import as_utc

NOT_FOUND_MESSAGE = "대화를 찾을 수 없습니다."
INVALID_QUESTIONNAIRE_MESSAGE = "이 대화에서 제출한 질문지가 아닙니다."
RESUMED_QUESTIONNAIRE_MESSAGE = "이미 이어서 처리한 질문지입니다."
INVALID_APPROVAL_MESSAGE = "이 대화에서 다시 짜기로 거부한 승인 건이 아닙니다."
RESUMED_APPROVAL_MESSAGE = "이미 이어서 처리한 승인 건입니다."
TURN_RUNNING_MESSAGE = "앞의 요청을 처리하는 중입니다."
UNKNOWN_CONNECTION_MESSAGE = "없는 연결을 골랐습니다."
UNTESTED_CONNECTION_MESSAGE = "연결 시험을 먼저 해 주세요."
UNKNOWN_MODEL_MESSAGE = "그 연결에 없는 모델입니다."
UNKNOWN_FILE_MESSAGE = "없는 파일입니다."
DELETED_FILE_MESSAGE = "지워진 파일입니다."
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


def list_sessions(session: Session, user: User) -> list[ChatSessionItem]:
    rows = chats.list_chats(session, user.id)
    retries = approvals.pending_retries(session, [c.id for c in rows])
    return [ChatSessionItem(**_out(c).model_dump(), pending_retries=len(retries.get(c.id, []))) for c in rows]


def detail(session: Session, user: User, chat_id: int) -> ChatSessionDetail:
    chat = _owned(session, user, chat_id)
    messages = [
        MessageOut(id=m.id, role=m.role, content=m.content_json, created_at=as_utc(m.created_at))
        for m in chats.messages(session, chat_id)
    ]
    retries = [
        RetryOut(approval_id=r.id, title=r.title, note=r.note, decided_by_name=r.decided_by or "",
                 decided_at=as_utc(r.decided_at))
        for r in approvals.pending_retries(session, [chat_id]).get(chat_id, [])
    ]
    attached = [ChatFileOut(file_id=f.id, name=f.name, kind=f.kind, status=f.status, deleted=f.deleted_at is not None)
                for f in file_store.session_files(session, chat_id)]
    return ChatSessionDetail(**_out(chat).model_dump(), running=turns.is_running(chat_id),
                             model=_model_out(session, chat_id), files=attached, messages=messages,
                             pending_retries=retries)


def _model_out(session: Session, chat_id: int) -> ChatModelOut | None:
    picked = assignments.chat_model(session, chat_id)
    if picked is None:
        return None
    return ChatModelOut(connection_id=picked.connection_id, model=picked.model,
                        routing_strategy=picked.routing_strategy)


def set_model(session: Session, user: User, chat_id: int, body: ChatModelIn) -> ChatModelOut:
    """이 대화에만 쓸 모델을 저장한다(그 연결의 대화용 모델만). 다음 턴의 대화 호출부터 쓴다.

    라우팅 기준은 라우터 모델(이름이 -router 로 끝남)에만 남긴다.
    """
    chat = _owned(session, user, chat_id)
    conn = session.get(LlmConnection, body.connection_id)
    if conn is None:
        raise ApiError(422, "invalid_request", UNKNOWN_CONNECTION_MESSAGE, {"connection_ids": [body.connection_id]})
    models = normalize_models(conn.models_json)
    if not models:
        raise ApiError(422, "connection_not_tested", UNTESTED_CONNECTION_MESSAGE)
    if not any(m["id"] == body.model and m["chat"] for m in models):
        raise ApiError(422, "unknown_model", UNKNOWN_MODEL_MESSAGE, {"model": body.model})
    routing = body.routing_strategy if _is_router(body.model) else None
    chat.model_connection_id, chat.model_name, chat.model_routing = body.connection_id, body.model, routing
    session.commit()
    return ChatModelOut(connection_id=body.connection_id, model=body.model, routing_strategy=routing)


def _is_router(model: str) -> bool:
    """화면의 isRouter 와 같은 규칙(/.-router$/)."""
    return len(model) > len("-router") and model.endswith("-router")


def clear_model(session: Session, user: User, chat_id: int) -> None:
    """기본(설정의 대화 배정)으로 돌린다."""
    chat = _owned(session, user, chat_id)
    chat.model_connection_id = chat.model_name = chat.model_routing = None
    session.commit()


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


def _check_approval(session: Session, chat_id: int, approval_id: int) -> None:
    """거부하고 다시 짜게 했고(rejected·retry) 이 대화에서 낸 것이며 아직 이어 가지 않은 승인 건만 받는다."""
    try:
        row = approvals.get(session, approval_id)
    except approvals.NotFound:
        row = None
    if row is None or row.status != "rejected" or not row.retry or row.chat_session_id != chat_id:
        raise ApiError(422, "invalid_approval", INVALID_APPROVAL_MESSAGE)
    if approvals.was_resumed(session, chat_id, approval_id):
        raise ApiError(422, "invalid_approval", RESUMED_APPROVAL_MESSAGE)


def _check_files(session: Session, file_ids: list[int]) -> None:
    """붙일 파일은 있고 지우지 않은 것만(보는 범위는 지금 회사 전체). 대화에 잇는 것은 턴이 사용자 메시지와 함께 한다."""
    for file_id in file_ids:
        row = session.get(FileRow, file_id)
        if row is None:
            raise ApiError(422, "invalid_file", UNKNOWN_FILE_MESSAGE, {"file_id": file_id})
        if row.deleted_at is not None:
            raise ApiError(422, "invalid_file", DELETED_FILE_MESSAGE, {"file_id": file_id})


def start_turn(session: Session, user: User, chat_id: int, body: MessageIn) -> StreamingResponse:
    """확인(404 → 422 질문지·승인 건·파일 → 409) 뒤 턴을 맡고 SSE 응답을 돌려준다(기다리는 동안 `: ping` 주석 줄)."""
    _owned(session, user, chat_id)
    if body.questionnaire_id is not None:
        _check_questionnaire(session, chat_id, body.questionnaire_id)
    if body.approval_id is not None:
        _check_approval(session, chat_id, body.approval_id)
    _check_files(session, body.file_ids)
    try:
        held = turns.claim(chat_id)
    except turns.TurnRunning:
        raise ApiError(409, "turn_running", TURN_RUNNING_MESSAGE) from None
    ui = UiContext(body.ui.program, body.ui.schedule_id, body.ui.selected_activity)
    stream = turn_stream(chat_id, user.id, body.text, ui, body.questionnaire_id, held, body.approval_id, body.file_ids)
    weakref.finalize(stream, turns.release, chat_id, held)  # 시작도 못 하고 버려진 응답도 턴을 놓게
    return StreamingResponse(stream, media_type="text/event-stream", headers=_SSE_HEADERS)


async def turn_stream(
    chat_id: int, user_id: int, text: str | None, ui: UiContext, questionnaire_id: int | None, held: turns.Claim,
    approval_id: int | None = None, file_ids: list[int] | None = None,
) -> AsyncIterator[str]:
    """턴의 사건을 SSE 글로. 스트림이 끝나거나 닫히면(연결 끊김) 턴을 놓는다."""
    try:
        with contextmanager(get_session)() as session:
            user = session.get(User, user_id)
            turn = run_turn(session, user, chat_id, text, ui, questionnaire_id=questionnaire_id,
                            approval_id=approval_id, file_ids=file_ids or ())
            async with aclosing(turn) as events:
                async for event in events:
                    yield to_sse(event)
    finally:
        turns.release(chat_id, held)
