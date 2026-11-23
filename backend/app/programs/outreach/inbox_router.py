from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ApiError
from app.programs.contacts.schemas import PersonDetail
from app.programs.outreach import inbox_service as service
from app.programs.outreach.inbox_service import (
    AcceptIn,
    AddPeerIn,
    AlertsOut,
    DecidedOut,
    ProposalOut,
    ReportOut,
    UnknownDetailOut,
    UnknownPeerOut,
)
from app.security.deps import require_contacts
from app.store.tables import User

# 들어온 문자 화면 API(Task 85). 관리자·사용자만(현장 관리자 403 field_no_contacts). 응답의 번호는 가린 꼴과 peer_key 뿐.
# 일정 없는 길(모르는 번호·일정 없는 보고·긴급 알림)과 일정의 길(보고·제안)을 한 라우터에 둔다.
# 이 라우터는 app/programs/outreach/router.py 가 import 해서 앱에 붙는다(main 은 router.py 만 읽는다).
inbox_router = APIRouter(tags=["outreach"], dependencies=[Depends(require_contacts)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(require_contacts)]
PeerKey = Annotated[str, Path(pattern=r"^[0-9a-f]{12}$")]
Status = Annotated[Literal["open", "reviewed", "all"], Query()]
SCHEDULE = "/api/schedules/{schedule_id}"


@inbox_router.get("/api/outreach/unknown")
def unknown(session: SessionDep) -> list[UnknownPeerOut]:
    """「모르는 번호」 묶음 — 일정 없는 문자·통화를 번호로 묶음(가린 번호·peer_key), 최근 것부터."""
    return service.unknown_list(session)


@inbox_router.get("/api/outreach/unknown/{peer_key}")
def unknown_peer(peer_key: PeerKey, session: SessionDep) -> UnknownDetailOut:
    """그 번호의 문자·통화 줄(오래된 것부터, 글의 번호는 가림). 없으면 404 peer_not_found."""
    return service.unknown_detail(session, peer_key)


@inbox_router.post(SCHEDULE + "/outreach/unknown/{peer_key}/contact")
def add_unknown_peer(schedule_id: int, peer_key: PeerKey, body: AddPeerIn, session: SessionDep) -> PersonDetail:
    """[주소록에 넣기] — 그 번호로 지금 일정에 사람을 만든다(사람 양식과 같은 검사, 협력사는 고르거나 새로)."""
    return service.add_peer(session, schedule_id, peer_key, body)


@inbox_router.get(SCHEDULE + "/outreach/reports")
def schedule_reports(schedule_id: int, session: SessionDep, status: Status = "open") -> list[ReportOut]:
    """이 일정의 보고(「문자로 받은 보고」·「전화로 받은 보고」·「내용 확인 필요」), 새것부터."""
    return service.reports(session, schedule_id, status)


@inbox_router.post(SCHEDULE + "/outreach/reports/{report_id}/review")
def review_schedule_report(schedule_id: int, report_id: int, session: SessionDep, user: UserDep) -> ReportOut:
    """[확인함]. 다른 일정의 보고 404, 이미 확인함 409."""
    return service.review(session, schedule_id, report_id, user)


@inbox_router.get("/api/outreach/reports")
def unassigned_reports(session: SessionDep, unassigned: Annotated[bool, Query()] = False,
                       status: Status = "open") -> list[ReportOut]:
    """일정 없는 보고(모르는 번호에서 온 것)만 — unassigned=1 이 꼭 있어야 한다."""
    if not unassigned:
        raise ApiError(422, "unassigned_only", "이 길은 일정 없는 보고만 읽습니다(unassigned=1).")
    return service.reports(session, None, status)


@inbox_router.post("/api/outreach/reports/{report_id}/review")
def review_unassigned_report(report_id: int, session: SessionDep, user: UserDep) -> ReportOut:
    """일정 없는 보고의 [확인함]. 일정 있는 보고는 404(그 일정의 길로)."""
    return service.review(session, None, report_id, user)


@inbox_router.get(SCHEDULE + "/contacts/proposals")
def proposals(schedule_id: int, session: SessionDep) -> list[ProposalOut]:
    """확인할 연락처 — 이 일정의 제안과 일정 없는 제안(받아들이면 이 일정에), 새것부터."""
    return service.proposals(session, schedule_id)


@inbox_router.post(SCHEDULE + "/contacts/proposals/{proposal_id}/accept")
def accept_proposal(schedule_id: int, proposal_id: int, body: AcceptIn, session: SessionDep,
                    user: UserDep) -> PersonDetail:
    """[주소록에 넣기] — 새 연락처를 지금 일정에 만들거나(협력사 하나) 그 사람의 언어를 바꾼다 → 그 사람."""
    return service.accept(session, schedule_id, proposal_id, body, user)


@inbox_router.post(SCHEDULE + "/contacts/proposals/{proposal_id}/reject")
def reject_proposal(schedule_id: int, proposal_id: int, session: SessionDep, user: UserDep) -> DecidedOut:
    """[버리기]."""
    return service.reject(session, schedule_id, proposal_id, user)


@inbox_router.get("/api/outreach/alerts")
def alerts(session: SessionDep, since: Annotated[datetime | None, Query()] = None) -> AlertsOut:
    """확인하지 않은 긴급 보고(since 뒤). 응답의 now 를 다음 since 로 쓴다."""
    return service.alerts(session, since)
