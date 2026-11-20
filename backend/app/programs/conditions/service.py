"""조건·규칙: 겹별 보기·미리 보기·확정·에이전트에게 맞추게 하기.

조건은 일정의 지금 버전에 저장된 dict 목록이다. 읽을 때마다 기본 규칙과 함께 조립(assemble_all)하고
점검(check)한다. 일정은 화면·점검과 같은 준비(harness.prepare)를 거쳐 run(compute → level(shift=True))한다.
한 요청 안에서 한 조건 목록의 점검과 계산은 쓸 때 한 번만 한다(_Side). 점검(check)은 하네스 안에서 따로 계산한다.
조건 줄마다 근거 검색으로 붙인 출처(evidence: 일정과 그 일정을 만든 초안의 링크)를 함께 보낸다.
- 미리 보기는 아무것도 저장하지 않는다. 저장된 버전이 계산되지 않아도 고친 조건을 미리 볼 수 있다(before 는 None).
- 확정은 Task 11 의 승인 판단(assess)과 승인 건(store.approvals, requested_kind "user")으로 간다: 승인이 필요하면
  pending 건, 아니면 그 자리에서 반영(status auto, 되돌릴 버전 restore_to). 반영한 버전의 by_kind 는 "user".
- 에이전트에게 맞추게 하기는 모든 변경을 확인한 뒤, 입력 조건 변경만 넣어 계산한 요청 글을 만든다(에이전트는 입력
  조건만 바꿀 수 있다 — 분야 규칙 변경은 [확정]으로). 그 사용자가 이 일정에 쓰던 「조건 맞추기」 대화가 있으면
  그것을, 없으면 새 대화를 쓴다(턴은 시작하지 않는다. 사용자가 대화 화면에서 보낸다).
확인 차례: 401 → 본문 422 invalid_request → 404 → 409 version_conflict → 변경 422 invalid_change·403 admin_only
→ 계산 422 schedule_invalid(까닭을 붙인 한국어).
"""

from dataclasses import dataclass, replace
from functools import cached_property

from sqlalchemy.orm import Session

from app.agent.approval import Assessment, assess
from app.core.cpm import CpmResult, ScheduleError
from app.core.model import Schedule
from app.errors import ApiError
from app.harness.assemble import assemble_all, prepare
from app.harness.checks import CheckReport, check
from app.harness.conditions import read_conditions
from app.programs.conditions import states, words
from app.programs.conditions.changes import apply_changes, input_only
from app.programs.conditions.preview_view import moved, side
from app.programs.conditions.schemas import (
    AskOut,
    ChangesIn,
    CommitOut,
    ConditionsOut,
    PreviewOut,
)
from app.store import approvals, chats
from app.store.drafts import violation_json
from app.store.evidence import for_conditions
from app.store.messages import schedule_error_message
from app.store.schedules import NotFound, get_record, load, run, to_json
from app.store.settings import approval_mode
from app.store.tables import ChatSession, ScheduleRecord, User
from app.store.versions import VersionConflict
from app.store.view import plan_with, view_of

CONFLICT_MESSAGE = "그 사이 일정이 바뀌었습니다. 다시 불러와 주세요."
NO_CHANGE_MESSAGE = "바뀌는 것이 없습니다."
AFTER_BROKEN = "바꾼 조건으로는 일정을 계산할 수 없습니다"
STORED_BROKEN_COMMIT = "지금 저장된 일정을 계산할 수 없어 확정할 수 없습니다"
STORED_BROKEN_AGENT = "지금 저장된 일정을 계산할 수 없어 에이전트에게 맡길 수 없습니다"


@dataclass(frozen=True)
class _Loaded:
    record: ScheduleRecord
    schedule: Schedule
    stored: list[dict]
    n: int


class _Side:
    """한 조건 목록(저장된 것 또는 바꾼 것)의 조립. 점검(report)과 계산(computed)은 처음 쓸 때 한 번만 한다."""

    def __init__(self, schedule: Schedule, stored: list[dict]) -> None:
        self.schedule, self.stored = schedule, stored
        self.readable, self.unreadable = read_conditions(stored)
        self.assembled = assemble_all(self.readable)

    @cached_property
    def report(self) -> CheckReport:
        return check(self.schedule, self.assembled)

    @cached_property
    def ready(self) -> Schedule:
        return prepare(self.schedule, self.readable)  # 화면·점검과 같은 준비

    @cached_property
    def computed(self) -> CpmResult | ScheduleError:
        try:
            return run(self.ready)
        except ScheduleError as e:
            return e

    @property
    def cpm(self) -> CpmResult | None:
        return None if isinstance(self.computed, ScheduleError) else self.computed


def _need(s: _Side, why: str) -> CpmResult:
    """계산 결과. 계산이 안 되면 422 schedule_invalid "<why>: <core 까닭>"."""
    if isinstance(s.computed, ScheduleError):
        e = s.computed
        raise ApiError(422, "schedule_invalid", f"{why}: {schedule_error_message(e)}", e.detail)
    return s.computed


def _load(session: Session, schedule_id: int, base_version: int | None = None) -> _Loaded:
    try:
        record = get_record(session, schedule_id)
    except NotFound:
        raise ApiError(404, "not_found", "일정을 찾을 수 없습니다.") from None
    schedule, stored, n = load(session, schedule_id)
    if base_version is not None and base_version != n:
        raise ApiError(409, "version_conflict", CONFLICT_MESSAGE, {"current": n})
    return _Loaded(record, schedule, stored, n)


def _with_evidence(session: Session, schedule_id: int, layers: dict) -> dict:
    """조건 줄마다 붙인 근거 [{id, title, url}](없으면 [])."""
    found = for_conditions(session, schedule_id)
    for row in (r for rows in layers.values() for r in rows):
        row["evidence"] = [{"id": e.id, "title": e.title, "url": e.url} for e in found.get(row["id"], [])]
    return layers


def _conditions_out(session: Session, loaded: _Loaded, s: _Side, user: User) -> ConditionsOut:
    layers = states.layers(loaded.schedule, s.assembled, s.report, user)
    return ConditionsOut.model_validate({
        "schedule_id": loaded.record.id, "name": loaded.record.name, "version": loaded.n,
        "layers": _with_evidence(session, loaded.record.id, layers),
        "summary": states.summary(s.report),
        "invalid": s.unreadable + s.report.invalid,
        "resources": to_json(loaded.schedule)["resources"],
    })


def get_conditions(session: Session, schedule_id: int, user: User) -> ConditionsOut:
    loaded = _load(session, schedule_id)
    return _conditions_out(session, loaded, _Side(loaded.schedule, loaded.stored), user)


def _changed(session: Session, schedule_id: int, body: ChangesIn, user: User) -> tuple[_Loaded, _Side, _Side]:
    """(불러온 것, 저장된 조건 쪽, 바꾼 조건 쪽). 확인 차례는 모듈 설명글."""
    loaded = _load(session, schedule_id, body.base_version)
    after_stored = apply_changes(loaded.stored, body.changes, user, loaded.schedule.resources)
    return loaded, _Side(loaded.schedule, loaded.stored), _Side(loaded.schedule, after_stored)


def preview(session: Session, schedule_id: int, body: ChangesIn, user: User) -> PreviewOut:
    """바꾼 조건으로 계산한 일정·위반·움직인 액티비티. 저장하지 않는다.

    view 의 Plan 칸과 상태는 바꾼 조건으로 계산한 Plan(확정하면 될 Plan)을 따른다. moved 는 Plan 날짜로
    before = 저장된 조건의 Plan, after = 바꾼 조건의 Plan 이다(간트 막대가 Plan 날짜라서).
    """
    loaded, before, after = _changed(session, schedule_id, body, user)
    cpm = _need(after, AFTER_BROKEN)
    saved = before.cpm  # 저장된 버전이 계산되지 않으면 None: 그래도 고친 조건은 미리 본다
    violations = after.report.violations
    plan_before = plan_with(loaded.schedule, loaded.stored, saved) if saved else None
    plan_after = plan_with(loaded.schedule, after.stored, cpm)
    return PreviewOut.model_validate({
        "feasible": not violations,
        "view": view_of(session, loaded.record.id, loaded.n, loaded.schedule, after.ready, cpm, plan_after),
        "before": side(saved, len(before.report.violations)),
        "after": side(cpm, len(violations)),
        "moved": moved(loaded.schedule, plan_before, plan_after) if plan_before and plan_after else [],
        "violations": [violation_json(v) for v in violations],
        "conditions": _conditions_out(session, loaded, after, user),
    })


def _effective(s: _Side) -> dict[str, tuple]:
    """조립한 조건을 id → (종류, 값, 켜짐) 으로(차례·글과 상관없이 비교하려고)."""
    return {c.id: (c.kind, c.params, c.enabled) for c in s.assembled}


def _assess(session: Session, loaded: _Loaded, before: _Side, after: _Side) -> Assessment:
    """Task 11 의 승인 판단·요약. 일정은 그대로이고 조건만 바뀐다. 읽지 못한 저장 조건도 invalid 로 센다.

    assess 는 저장 모양 조건으로 양쪽을 다시 계산한다(Task 11 의 비교 그대로). 부르기 전에 양쪽이 계산되는지 본다.
    """
    report = replace(after.report, invalid=after.unreadable + after.report.invalid)
    return assess(loaded.schedule, loaded.schedule, before.stored, after.stored, report, mode=approval_mode(session))


def commit(session: Session, schedule_id: int, body: ChangesIn, user: User) -> CommitOut:
    """승인 판단에 따라 승인 건(pending)을 만들거나 바로 반영한다. 바뀌는 것이 없으면 422 no_change."""
    loaded, before, after = _changed(session, schedule_id, body, user)
    if _effective(before) == _effective(after):
        raise ApiError(422, "no_change", NO_CHANGE_MESSAGE)
    _need(before, STORED_BROKEN_COMMIT)
    _need(after, AFTER_BROKEN)
    result = _assess(session, loaded, before, after)
    rows = result.summary["conditions_changed"]
    row = approvals.create(
        session, kind="change", title=words.approval_title(rows), reasons_json=list(result.decision.reasons),
        schedule_id=loaded.record.id, draft_id=None, base_version=loaded.n, summary_json=result.summary,
        diff_json=result.diff, snapshot_json=to_json(loaded.schedule), conditions_json=after.stored, changes_json=[],
        status="pending", request=words.approval_request(rows), chat_session_id=None, requested_by=user.name,
        requested_kind="user",
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


def _chat_for(session: Session, user: User, record: ScheduleRecord) -> ChatSession:
    """그 사용자가 이 일정에 쓰던 가장 최근 「조건 맞추기」 대화, 없으면 새 대화."""
    title = words.chat_title(record.name)
    for chat in chats.list_chats(session, user.id):  # 새것부터
        if chat.schedule_id == record.id and chat.title == title:
            return chat
    chat = chats.create_chat(session, user_id=user.id, schedule_id=record.id)
    chat.title = title
    session.commit()
    return chat


def ask_agent(session: Session, schedule_id: int, body: ChangesIn, user: User) -> AskOut:
    """모든 변경을 확인하고, 입력 조건 변경만 넣어 계산한 요청 글과 대화를 돌려준다."""
    loaded, before, _ = _changed(session, schedule_id, body, user)  # 모든 변경 확인(403·422)
    kept, domain_changed = input_only(loaded.stored, body.changes)
    after = _Side(loaded.schedule, apply_changes(loaded.stored, kept, user, loaded.schedule.resources))
    saved = _need(before, STORED_BROKEN_AGENT)
    cpm = _need(after, AFTER_BROKEN)
    rows = _assess(session, loaded, before, after).summary["conditions_changed"] if kept else []
    text = words.agent_request(loaded.record.name, rows, (saved.finish, cpm.finish), after.report.violations,
                               domain_changed)
    return AskOut(chat_session_id=_chat_for(session, user, loaded.record).id, text=text)
