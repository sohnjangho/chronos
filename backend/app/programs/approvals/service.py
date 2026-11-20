"""승인함: 목록·상세·배지 수·결정, 승인 수준 설정.

로그인한 누구나 같은 승인함을 보고 결정한다. 결정은 pending 인 건에만 한다(아니면 409). 두 사람이 같이 결정해도
하나만 적힌다(store.approvals.record_decision 의 조건부 UPDATE, 진 쪽은 반영까지 되돌림).
승인은 store.approvals.apply 로 반영한다(첫 저장은 새 일정 + Plan, 고침은 새 버전). 그 사이 일정이 바뀌었으면
반영하지 않고 status 를 conflict 로 남긴 뒤 409 를 준다.
"""

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.programs.approvals.schemas import (
    ApprovalDetail,
    ApprovalList,
    ApprovalOut,
    CountOut,
    DecideIn,
    DecideOut,
    ModeIO,
)
from app.store import approvals
from app.store.settings import approval_mode, set_approval_mode
from app.store.tables import Approval, User
from app.store.versions import VersionConflict

NOT_FOUND_MESSAGE = "승인 건을 찾을 수 없습니다."
CONFLICT_MESSAGE = "그 사이 일정이 바뀌었습니다. 에이전트에게 다시 요청해 주세요."
ALREADY_DECIDED_MESSAGE = "이미 결정된 건입니다."
NOTE_REQUIRED_MESSAGE = "다시 짜게 하려면 이유를 적어 주세요."


def _get(session: Session, approval_id: int) -> Approval:
    try:
        return approvals.get(session, approval_id)
    except approvals.NotFound:
        raise ApiError(404, "not_found", NOT_FOUND_MESSAGE) from None


def _out(row: Approval) -> dict:
    return {
        "id": row.id, "kind": row.kind, "title": row.title, "status": row.status, "reasons": row.reasons_json,
        "schedule_id": row.schedule_id, "draft_id": row.draft_id, "base_version": row.base_version,
        "version": row.version, "restore_to": row.restore_to, "retry": row.retry, "request": row.request,
        "chat_session_id": row.chat_session_id, "requested_by": row.requested_by, "decided_by": row.decided_by,
        "note": row.note, "created_at": row.created_at, "decided_at": row.decided_at, "summary": row.summary_json,
    }


def list_approvals(session: Session, status: str) -> ApprovalList:
    items = [ApprovalOut(**_out(r)) for r in approvals.listed(session, status)]
    return ApprovalList(mode=approval_mode(session), items=items)


def detail(session: Session, approval_id: int) -> ApprovalDetail:
    row = _get(session, approval_id)
    return ApprovalDetail(**_out(row), mode=approval_mode(session), diff=row.diff_json)


def count(session: Session) -> CountOut:
    return CountOut(pending=approvals.pending_count(session))


def _close(session: Session, row: Approval, status: str, user: User, note: str, retry: bool = False) -> None:
    """결정을 적고 commit 한다. 그 사이 다른 사람이 먼저 결정했으면 모두 되돌리고 409 already_decided."""
    if not approvals.record_decision(session, row, status, by=user.name, note=note, retry=retry):
        session.rollback()
        raise ApiError(409, "already_decided", ALREADY_DECIDED_MESSAGE)
    session.commit()


def _approve(session: Session, row: Approval, user: User, note: str) -> None:
    try:
        approvals.apply(session, row, by_name=user.name)
    except VersionConflict as e:
        _close(session, row, "conflict", user, note)  # 반영하지 않고 충돌로 남긴다
        raise ApiError(409, "version_conflict", CONFLICT_MESSAGE, {"current": e.current}) from None
    _close(session, row, "approved", user, note)


def decide(session: Session, approval_id: int, body: DecideIn, user: User) -> DecideOut:
    """확인 차례: 404 → 409 already_decided → 422 note_required → 반영(409 version_conflict 가능)."""
    row = _get(session, approval_id)
    if row.status != "pending":
        raise ApiError(409, "already_decided", ALREADY_DECIDED_MESSAGE)
    if body.decision == "reject_retry" and not body.note:
        raise ApiError(422, "note_required", NOTE_REQUIRED_MESSAGE)
    if body.decision == "approve":
        _approve(session, row, user, body.note)
    else:
        _close(session, row, "rejected", user, body.note, retry=body.decision == "reject_retry")
    return DecideOut(status=row.status, version=row.version, schedule_id=row.schedule_id,
                     chat_session_id=row.chat_session_id)


def get_mode(session: Session) -> ModeIO:
    return ModeIO(mode=approval_mode(session))


def put_mode(session: Session, body: ModeIO) -> ModeIO:
    set_approval_mode(session, body.mode)
    return get_mode(session)
