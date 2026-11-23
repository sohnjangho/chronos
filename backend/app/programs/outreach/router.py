from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.outreach import service
from app.programs.outreach.calls_router import calls_router  # noqa: F401 — 통화 API(Task 91), main 은 router.py 만 읽는다
from app.programs.outreach.schemas import (
    AgentDraftIn,
    MessageIn,
    MessageOut,
    MessagePatch,
    MessageResult,
    ResendOut,
    ThreadOut,
)
from app.security.deps import require_contacts
from app.store.tables import User

# 「연락처」 프로그램의 메시지(대화) API. 관리자·사용자만(현장 관리자 403 field_no_contacts). 다른 일정의 줄·연락처는 404.
# 보내기는 모두 나가는 문(gate.dispatch)을 지나고, 판정은 막힌 것도 200 으로 돌려준다. 응답에 번호는 없다.
router = APIRouter(prefix="/api/schedules", tags=["outreach"], dependencies=[Depends(require_contacts)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(require_contacts)]


@router.get("/{schedule_id}/outreach/threads/{contact_id}")
def thread(
    schedule_id: int, contact_id: int, session: SessionDep, user: UserDep,
    before: Annotated[int | None, Query(ge=1)] = None, limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ThreadOut:
    """그 사람과의 대화: 가장 최근 limit 개(오래된 것부터). before = 메시지 id(그보다 앞 것만)."""
    return service.thread(session, schedule_id, contact_id, before, limit, user)


@router.post("/{schedule_id}/outreach/messages")
async def create_message(schedule_id: int, body: MessageIn, session: SessionDep, user: UserDep) -> MessageResult:
    """초안을 만들고, send 면 나가는 문에 넣는다 → {message, outcome | null}. 막힌 것도 200."""
    return await service.create(session, schedule_id, body, user)


@router.post("/{schedule_id}/outreach/messages/agent-draft")
async def agent_draft(schedule_id: int, body: AgentDraftIn, session: SessionDep, user: UserDep) -> MessageOut:
    """[에이전트에게 초안 맡기기] → 모델이 쓴 초안 줄(origin agent, 보내지 않음). 거절 409, 모델 실패 503 draft_failed."""
    return await service.agent_draft(session, schedule_id, body, user)


@router.patch("/{schedule_id}/outreach/messages/{message_id}")
def patch_message(schedule_id: int, message_id: int, body: MessagePatch, session: SessionDep, user: UserDep) -> MessageOut:
    """초안만(본문·채널·작업). 그 밖은 409 not_draft."""
    return service.patch(session, schedule_id, message_id, body, user)


@router.delete("/{schedule_id}/outreach/messages/{message_id}", status_code=204)
def delete_message(schedule_id: int, message_id: int, session: SessionDep) -> Response:
    """초안만. 그 밖은 409 not_draft."""
    service.remove(session, schedule_id, message_id)
    return Response(status_code=204)


@router.post("/{schedule_id}/outreach/messages/{message_id}/send")
async def send_message(schedule_id: int, message_id: int, session: SessionDep, user: UserDep) -> MessageResult:
    """초안·예약을 나가는 문에 넣는다 → {message, outcome}. 끝난 줄은 409 not_sendable(다시 보내기는 resend)."""
    return await service.send(session, schedule_id, message_id, user)


@router.post("/{schedule_id}/outreach/messages/{message_id}/cancel")
def cancel_message(schedule_id: int, message_id: int, session: SessionDep, user: UserDep) -> MessageOut:
    """예약 → 초안. 예약이 아니면 409 not_scheduled."""
    return service.cancel(session, schedule_id, message_id, user)


@router.post("/{schedule_id}/outreach/messages/{message_id}/resend")
def resend_message(schedule_id: int, message_id: int, session: SessionDep, user: UserDep) -> ResendOut:
    """실패·확인 필요 줄 → 같은 글의 새 초안(보내지 않음) → {message, warning}. 그 밖은 409 not_resendable."""
    return service.resend(session, schedule_id, message_id, user)
