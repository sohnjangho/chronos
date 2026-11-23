from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.outreach import calls_service
from app.programs.outreach.calls_schemas import (
    CallDetail,
    CallIn,
    CallOut,
    CallPatch,
    CallResult,
    ConfirmIn,
    ScheduleIn,
)
from app.security.deps import require_contacts
from app.store.tables import User

# 「연락처」 프로그램의 통화 API. 관리자·사용자만(현장 관리자 403 field_no_contacts). 다른 일정의 줄·연락처는 404.
# 걸기는 나가는 문(gate.dispatch)을 지나고, 판정은 막힌 것도 200 으로 돌려준다. 응답에 번호는 없다.
# 이 라우터는 app/programs/outreach/router.py 가 import 해서 앱에 붙는다(main 은 router.py 만 읽는다).
calls_router = APIRouter(prefix="/api/schedules", tags=["outreach"], dependencies=[Depends(require_contacts)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(require_contacts)]
CALLS = "/{schedule_id}/outreach/calls"
ONE = CALLS + "/{call_id}"


@calls_router.get(CALLS)
def list_calls(schedule_id: int, session: SessionDep,
               contact_id: Annotated[int | None, Query(ge=1)] = None) -> list[CallOut]:
    """그 일정의 통화(contact_id 를 주면 그 사람 것만), 최근 것부터."""
    return calls_service.listed(session, schedule_id, contact_id)


@calls_router.get(ONE)
def get_call(schedule_id: int, call_id: int, session: SessionDep) -> CallDetail:
    """한 통화 + 받아쓰기·받은 보고(번호는 가린 꼴)."""
    return calls_service.detail(session, schedule_id, call_id)


@calls_router.post(CALLS)
def create_call(schedule_id: int, body: CallIn, session: SessionDep, user: UserDep) -> CallOut:
    """통화 초안(걸지 않음)."""
    return calls_service.create(session, schedule_id, body, user)


@calls_router.patch(ONE)
def patch_call(schedule_id: int, call_id: int, body: CallPatch, session: SessionDep) -> CallOut:
    """초안만. 그 밖은 409 not_draft. 승인이 아니다."""
    return calls_service.patch(session, schedule_id, call_id, body)


@calls_router.delete(ONE, status_code=204)
def delete_call(schedule_id: int, call_id: int, session: SessionDep) -> Response:
    """초안만. 그 밖은 409 not_draft."""
    calls_service.remove(session, schedule_id, call_id)
    return Response(status_code=204)


@calls_router.post(ONE + "/place")
async def place_call(schedule_id: int, call_id: int, session: SessionDep, user: UserDep) -> CallResult:
    """나가는 문에 넣는다 → {call, outcome}. 막힌 것도 200. 끝난 줄은 409 not_sendable(다시 걸기는 redial)."""
    return await calls_service.place(session, schedule_id, call_id, user)


@calls_router.post(ONE + "/schedule")
def schedule_call(schedule_id: int, call_id: int, body: ScheduleIn, session: SessionDep, user: UserDep) -> CallOut:
    """그 시각에 예약(문이 누른 사람의 결정을 적는다). 근무시간 밖 422 outside_hours, 지난 시각 422 past_time,
    예약할 수 없는 상태·문이 예약하지 않음 409 not_schedulable."""
    return calls_service.schedule(session, schedule_id, call_id, body, user)


@calls_router.post(ONE + "/cancel")
def cancel_call(schedule_id: int, call_id: int, session: SessionDep) -> CallOut:
    """예약 → 초안. 예약이 아니면 409 not_scheduled."""
    return calls_service.cancel(session, schedule_id, call_id)


@calls_router.post(ONE + "/hangup")
def hangup_call(schedule_id: int, call_id: int, session: SessionDep) -> CallOut:
    """진행 중인 통화를 끊는다(통화 일꾼 — runner.hangup 은 동기이고 스레드에서 불러도 된다). 아니면 409 not_live."""
    return calls_service.hangup(session, schedule_id, call_id)


@calls_router.post(ONE + "/redial")
def redial_call(schedule_id: int, call_id: int, session: SessionDep, user: UserDep) -> CallOut:
    """받지 않음·통화 중·실패 → 같은 내용의 새 초안(걸지 않음). 그 밖은 409 not_redialable."""
    return calls_service.redial(session, schedule_id, call_id, user)


@calls_router.post(ONE + "/confirm")
def confirm_call(schedule_id: int, call_id: int, body: ConfirmIn, session: SessionDep, user: UserDep) -> CallOut:
    """끝난 통화의 결과를 확정(confirmed_by = 로그인한 사람). 끝나지 않았으면 409 not_completed."""
    return calls_service.confirm(session, schedule_id, call_id, body, user)


@calls_router.get(ONE + "/recording")
def get_recording(schedule_id: int, call_id: int, session: SessionDep) -> FileResponse:
    """녹음 파일(저장해 두지 않게 no-store). 녹음이 없으면 없는 통화와 같은 404. 이름·머리에 번호 없음."""
    path, name = calls_service.recording(session, schedule_id, call_id)
    return FileResponse(path, media_type=calls_service.audio_type(path), filename=name, content_disposition_type="inline",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
