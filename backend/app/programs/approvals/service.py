"""승인함: 목록·상세·배지 수·결정, 승인 수준 설정.

로그인한 누구나 같은 승인함을 보고 결정한다. 결정은 pending 인 건에만 한다(아니면 409). 두 사람이 같이 결정해도
하나만 적힌다(store.approvals.record_decision 의 조건부 UPDATE, 진 쪽은 반영까지 되돌림).
승인은 store.approvals.apply 로 반영한다(첫 저장은 새 일정 + 「처음 계획」 표시, 고침은 새 버전). 그 사이 일정이 바뀌었으면
반영하지 않고 status 를 conflict 로 남긴 뒤 409 를 준다. 거부·충돌은 이어진 것(만약에 복사본)에도 알린다(store.links,
결정과 같은 commit).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.proposals import actual_dates_problem, actuals_blocked
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
from app.programs.progress.field import legacy_photo
from app.store import approvals, chats, links
from app.store.schedules import NotFound, from_json, load
from app.store.settings import approval_mode, set_approval_mode
from app.store.tables import Approval, FieldItem, User
from app.store.versions import VersionConflict

NOT_FOUND_MESSAGE = "승인 건을 찾을 수 없습니다."
CONFLICT_MESSAGE = "그 사이 일정이 바뀌었습니다. 에이전트에게 다시 요청해 주세요."
ALREADY_DECIDED_MESSAGE = "이미 결정된 건입니다."
NOTE_REQUIRED_MESSAGE = "다시 짜게 하려면 이유를 적어 주세요."
DRAFT_USED_MESSAGE = "이미 저장한 초안입니다."
OLD_PHOTO_MESSAGE = "이전 방식으로 만든 판독이라 반영할 수 없습니다 — 사진을 다시 올려 주세요"


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


def _blocked(session: Session, row: Approval) -> str | None:
    """반영할 수 없는 까닭. 이 건을 낸 사진 항목이 예전 방식(F1 이전, 지어낸 숫자)이면(재확인 #14) — 현장 허브와 같은 기준
    (progress.field.legacy_photo). 새 방식이 읽지 못해 사람이 손으로 넣은 것은 막지 않는다. 저장된 줄은 바꾸지 않는다."""
    photo = session.scalars(select(FieldItem).where(FieldItem.approval_id == row.id, FieldItem.kind == "photo")).first()
    if photo is not None and legacy_photo(photo):
        return OLD_PHOTO_MESSAGE
    return _actuals_blocked(session, row)


def _actuals_blocked(session: Session, row: Approval) -> str | None:
    """반영하면 실적 날짜가 Data Date 뒤이거나 실제 시작이 착공일 앞이 되는 건(재확인 2, #13·#18)의 까닭. 규칙 건은 일정이 없다."""
    if row.kind == "rule" or not row.snapshot_json:
        return None
    before = None
    if row.kind == "change":
        try:
            before = load(session, row.schedule_id, row.base_version)[0]
        except NotFound:
            before = None
    after = from_json(row.snapshot_json)
    problem = actual_dates_problem(before, after)
    return actuals_blocked(after, problem) if problem is not None else None


def detail(session: Session, approval_id: int) -> ApprovalDetail:
    row = _get(session, approval_id)
    return ApprovalDetail(**_out(row), mode=approval_mode(session), diff=row.diff_json, blocked=_blocked(session, row))


def count(session: Session) -> CountOut:
    return CountOut(pending=approvals.pending_count(session))


def _finish_waiting_workflow(session: Session, row: Approval, status: str, retry: bool) -> None:
    """결재가 최종 승인/반려(재요청 제외)되면 해당 채팅 세션의 대기 중 워크플로우를 닫는다."""
    if retry or row.chat_session_id is None:
        return
    from datetime import UTC, datetime
    from sqlalchemy import select
    from app.store.tables import WorkflowRun

    waiting = session.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.chat_session_id == row.chat_session_id, WorkflowRun.status == "waiting")
        .order_by(WorkflowRun.id.desc())
    ).first()
    if waiting is None:
        return
    waiting.status = "done" if status == "approved" else "stopped"
    waiting.ended_at = datetime.now(UTC)


def _close(session: Session, row: Approval, status: str, user: User, note: str, retry: bool = False) -> None:
    """결정을 적고 commit 한다. 그 사이 다른 사람이 먼저 결정했으면 모두 되돌리고 409 already_decided."""
    if not approvals.record_decision(session, row, status, by=user.name, note=note, retry=retry):
        session.rollback()
        raise ApiError(409, "already_decided", ALREADY_DECIDED_MESSAGE)
    _finish_waiting_workflow(session, row, status, retry)
    session.commit()


def _approve(session: Session, row: Approval, user: User, note: str) -> None:
    try:
        approvals.apply(session, row, by_name=user.name)
    except VersionConflict as e:
        links.after_conflict(session, row)
        _close(session, row, "conflict", user, note)  # 반영하지 않고 충돌로 남긴다
        raise ApiError(409, "version_conflict", CONFLICT_MESSAGE, {"current": e.current}) from None
    except approvals.DraftUsed:
        links.after_conflict(session, row)
        _close(session, row, "conflict", user, note)
        raise ApiError(409, "draft_used", DRAFT_USED_MESSAGE) from None
    _close(session, row, "approved", user, note)


def _owner_is(session: Session, row: Approval, user: User) -> bool:
    if row.chat_session_id is None:
        return False
    try:
        return chats.get_chat(session, row.chat_session_id).user_id == user.id
    except chats.NotFound:
        return False


def decide(session: Session, approval_id: int, body: DecideIn, user: User) -> DecideOut:
    """확인 차례: 404 → 409 already_decided → 422 note_required → 반영(409 version_conflict·draft_used 가능)."""
    row = _get(session, approval_id)
    if row.status != "pending":
        raise ApiError(409, "already_decided", ALREADY_DECIDED_MESSAGE)
    if body.decision == "reject_retry" and not body.note:
        raise ApiError(422, "note_required", NOTE_REQUIRED_MESSAGE)
    if body.decision == "approve" and (blocked := _blocked(session, row)) is not None:
        raise ApiError(422, "photo_unread" if blocked == OLD_PHOTO_MESSAGE else "actual_dates", blocked)
    if body.decision == "approve":
        _approve(session, row, user, body.note)
    else:
        links.after_reject(session, row)
        _close(session, row, "rejected", user, body.note, retry=body.decision == "reject_retry")
    return DecideOut(status=row.status, version=row.version, schedule_id=row.schedule_id,
                     chat_session_id=row.chat_session_id, owner_is_decider=_owner_is(session, row, user))


def get_mode(session: Session) -> ModeIO:
    return ModeIO(mode=approval_mode(session))


def put_mode(session: Session, body: ModeIO) -> ModeIO:
    set_approval_mode(session, body.mode)
    return get_mode(session)
