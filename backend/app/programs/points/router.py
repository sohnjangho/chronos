from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.points import service
from app.programs.points.service import ContactIn, QuoteIn, RetryIn
from app.security.deps import current_user, require_contacts
from app.store.tables import User

# 관리 포인트(계획 5): 조회와 [근거 문장 보기]는 일정 읽기와 같은 범위(로그인한 누구나). 담당자 연락(사람 고르기·초안)은
# 연락처 권한(현장 관리자 403 field_no_contacts). 응답에 전화번호는 없다. 보내기는 기존 메시지·통화 API 의 사람 [보내기]뿐.
router = APIRouter(prefix="/api/schedules", tags=["points"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
ContactsUser = Annotated[User, Depends(require_contacts)]
UserDep = Annotated[User, Depends(current_user)]


@router.get("/{schedule_id}/points")
def get_points(schedule_id: int, session: SessionDep, user: UserDep, what_if: Annotated[bool, Query()] = False) -> dict:
    """지금 버전의 포인트·마지막 차이·바깥 위험·근거 문장 상태·카드(바뀜이 없으면 null). what_if = 지연 분석의 가정.
    현장 관리자에게는 카드 actions 에 contact 가 없다."""
    return service.view(session, schedule_id, what_if=what_if, field=user.role == "field")


@router.post("/{schedule_id}/points/risks/retry")
def retry_risks(schedule_id: int, body: RetryIn, session: SessionDep, user: UserDep) -> dict:
    """「다시 찾기」: 실패(멈춘 것 포함)했거나 아직 찾지 않은(not_started) 바깥 위험 찾기만 띄운다 → 조회와 같은 꼴.
    아니면 409 not_failed."""
    return service.retry_risks(session, schedule_id, body, field=user.role == "field")


@router.post("/{schedule_id}/points/{activity_id}/quotes/{kind}")
async def find_quote(schedule_id: int, activity_id: str, kind: str, body: QuoteIn, session: SessionDep) -> dict:
    """[근거 문장 보기]·「다시 찾기」(retry) → 근거 문장 상태(pending·ready·failed). 찾기는 뒤에서 한다."""
    return await service.quote(session, schedule_id, activity_id, kind, body)


@router.get("/{schedule_id}/points/{activity_id}/contact")
def contact_people(schedule_id: int, activity_id: str, session: SessionDep, _: ContactsUser,
                   what_if: Annotated[bool, Query()] = False) -> dict:
    """그 작업 담당 협력사의 연락처(번호 없음)."""
    return service.people(session, schedule_id, activity_id, what_if=what_if)


@router.post("/{schedule_id}/points/{activity_id}/contact")
async def contact(schedule_id: int, activity_id: str, body: ContactIn, session: SessionDep, user: ContactsUser) -> dict:
    """고른 사람에게 보낼 확인 글(preview) 또는 초안(보내지 않음) → {preview, body | purpose·questions | card}."""
    return await service.contact(session, schedule_id, activity_id, body, user)
