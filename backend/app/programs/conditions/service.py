"""조건·규칙: 겹별 보기·미리 보기·확정·에이전트에게 맞추게 하기.

조건은 일정의 지금 버전에 저장된 dict 목록이다. 읽을 때마다 기본 규칙과 함께 조립(assemble_all)하고
점검(check)한다. 화면 날짜·점검과 같은 준비(조건 넣기 → compute → level(shift=True))를 쓴다.
- 미리 보기는 아무것도 저장하지 않는다.
- 확정은 Task 11 의 승인 판단(assess)과 승인 건(store.approvals)으로 간다: 승인이 필요하면 pending 건,
  아니면 그 자리에서 반영(status auto, 되돌릴 버전 restore_to).
- 에이전트에게 맞추게 하기는 변경을 미리 보기처럼 확인한 뒤 그 사용자의 새 대화를 만들고 요청 글을 돌려준다
  (턴은 시작하지 않는다. 사용자가 대화 화면에서 보낸다).
확인 차례: 401 → 본문 422 invalid_request → 404 → 409 version_conflict → 변경 422 invalid_change·403 admin_only
→ 계산 422 schedule_invalid.
"""

from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from app.agent.approval import Assessment, assess
from app.core.cpm import CpmResult, ScheduleError
from app.core.model import Schedule
from app.errors import ApiError
from app.harness.assemble import apply_to_schedule, assemble_all
from app.harness.checks import CheckReport, check
from app.harness.conditions import Condition, read_conditions
from app.programs.conditions import states, words
from app.programs.conditions.changes import apply_changes
from app.programs.conditions.preview_view import moved, preview_view, side
from app.programs.conditions.schemas import (
    AskOut,
    ChangesIn,
    CommitOut,
    ConditionsOut,
    PreviewOut,
)
from app.store import approvals, chats
from app.store.drafts import violation_json
from app.store.messages import schedule_error_message
from app.store.schedules import NotFound, get_record, load, run, to_json
from app.store.settings import approval_mode
from app.store.tables import ScheduleRecord, User
from app.store.versions import VersionConflict

CONFLICT_MESSAGE = "그 사이 일정이 바뀌었습니다. 다시 불러와 주세요."
NO_CHANGE_MESSAGE = "바뀌는 것이 없습니다."


@dataclass(frozen=True)
class _Loaded:
    record: ScheduleRecord
    schedule: Schedule
    stored: list[dict]
    n: int


@dataclass(frozen=True)
class _Side:
    """한 조건 목록(저장된 것 또는 바꾼 것)의 조립과 점검."""

    stored: list[dict]
    assembled: list[Condition]
    unreadable: list[dict]
    report: CheckReport


def _load(session: Session, schedule_id: int, base_version: int | None = None) -> _Loaded:
    try:
        record = get_record(session, schedule_id)
    except NotFound:
        raise ApiError(404, "not_found", "일정을 찾을 수 없습니다.") from None
    schedule, stored, n = load(session, schedule_id)
    if base_version is not None and base_version != n:
        raise ApiError(409, "version_conflict", CONFLICT_MESSAGE, {"current": n})
    return _Loaded(record, schedule, stored, n)


def _side(schedule: Schedule, stored: list[dict]) -> _Side:
    readable, unreadable = read_conditions(stored)
    assembled = assemble_all(readable)
    return _Side(stored, assembled, unreadable, check(schedule, assembled))


def _computed(schedule: Schedule, s: _Side) -> tuple[Schedule, CpmResult]:
    """조건을 넣은 일정과 화면 날짜. 계산이 안 되면 422 schedule_invalid."""
    ready = apply_to_schedule(schedule, s.assembled)
    try:
        return ready, run(ready)
    except ScheduleError as e:
        raise ApiError(422, "schedule_invalid", schedule_error_message(e), e.detail) from None


def _conditions_out(loaded: _Loaded, s: _Side, user: User) -> ConditionsOut:
    return ConditionsOut.model_validate({
        "schedule_id": loaded.record.id, "name": loaded.record.name, "version": loaded.n,
        "layers": states.layers(loaded.schedule, s.assembled, s.report, user),
        "summary": states.summary(s.report),
        "invalid": s.unreadable + s.report.invalid,
        "resources": to_json(loaded.schedule)["resources"],
    })


def get_conditions(session: Session, schedule_id: int, user: User) -> ConditionsOut:
    loaded = _load(session, schedule_id)
    return _conditions_out(loaded, _side(loaded.schedule, loaded.stored), user)


def _changed(session: Session, schedule_id: int, body: ChangesIn, user: User) -> tuple[_Loaded, _Side, _Side]:
    """(불러온 것, 저장된 조건 쪽, 바꾼 조건 쪽). 확인 차례는 모듈 설명글."""
    loaded = _load(session, schedule_id, body.base_version)
    after_stored = apply_changes(loaded.stored, body.changes, user)
    return loaded, _side(loaded.schedule, loaded.stored), _side(loaded.schedule, after_stored)


def preview(session: Session, schedule_id: int, body: ChangesIn, user: User) -> PreviewOut:
    """바꾼 조건으로 계산한 일정·위반·움직인 액티비티. 저장하지 않는다."""
    loaded, before, after = _changed(session, schedule_id, body, user)
    _, saved = _computed(loaded.schedule, before)
    ready, cpm = _computed(loaded.schedule, after)
    violations = after.report.violations
    return PreviewOut.model_validate({
        "feasible": not violations,
        "view": preview_view(session, loaded.record, loaded.schedule, ready, cpm, loaded.n, saved),
        "before": side(saved, len(before.report.violations)),
        "after": side(cpm, len(violations)),
        "moved": moved(loaded.schedule, saved, cpm),
        "violations": [violation_json(v) for v in violations],
        "conditions": _conditions_out(loaded, after, user),
    })


def _effective(s: _Side) -> dict[str, tuple]:
    """조립한 조건을 id → (종류, 값, 켜짐) 으로(차례·글과 상관없이 비교하려고)."""
    return {c.id: (c.kind, c.params, c.enabled) for c in s.assembled}


def _assess(session: Session, loaded: _Loaded, before: _Side, after: _Side) -> Assessment:
    """Task 11 의 승인 판단·요약. 일정은 그대로이고 조건만 바뀐다. 읽지 못한 저장 조건도 invalid 로 센다."""
    report = replace(after.report, invalid=after.unreadable + after.report.invalid)
    return assess(loaded.schedule, loaded.schedule, before.stored, after.stored, report, mode=approval_mode(session))


def commit(session: Session, schedule_id: int, body: ChangesIn, user: User) -> CommitOut:
    """승인 판단에 따라 승인 건(pending)을 만들거나 바로 반영한다. 바뀌는 것이 없으면 422 no_change."""
    loaded, before, after = _changed(session, schedule_id, body, user)
    if _effective(before) == _effective(after):
        raise ApiError(422, "no_change", NO_CHANGE_MESSAGE)
    _computed(loaded.schedule, after)
    result = _assess(session, loaded, before, after)
    rows = result.summary["conditions_changed"]
    row = approvals.create(
        session, kind="change", title=words.approval_title(rows), reasons_json=list(result.decision.reasons),
        schedule_id=loaded.record.id, draft_id=None, base_version=loaded.n, summary_json=result.summary,
        diff_json=result.diff, snapshot_json=to_json(loaded.schedule), conditions_json=after.stored, changes_json=[],
        status="pending", request=words.approval_request(rows), chat_session_id=None, requested_by=user.name,
    )
    if not result.decision.needs_approval:
        try:
            approvals.apply(session, row, by_name=user.name)
        except VersionConflict as e:
            session.rollback()
            raise ApiError(409, "version_conflict", CONFLICT_MESSAGE, {"current": e.current}) from None
        row.status, row.restore_to = "auto", loaded.n
    session.commit()
    return CommitOut(applied=row.status == "auto", version=row.version, approval_id=row.id)


def ask_agent(session: Session, schedule_id: int, body: ChangesIn, user: User) -> AskOut:
    """변경을 확인하고(미리 보기와 같은 확인) 그 사용자의 새 대화와 요청 글을 만든다."""
    loaded, before, after = _changed(session, schedule_id, body, user)
    _, saved = _computed(loaded.schedule, before)
    _, cpm = _computed(loaded.schedule, after)
    rows = _assess(session, loaded, before, after).summary["conditions_changed"]
    text = words.agent_request(loaded.record.name, rows, (saved.finish, cpm.finish), after.report.violations)
    chat = chats.create_chat(session, user_id=user.id, schedule_id=loaded.record.id)
    chat.title = words.chat_title(loaded.record.name)
    session.commit()
    return AskOut(chat_session_id=chat.id, text=text)
