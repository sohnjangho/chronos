"""일정 변경 제안의 공통 길(propose): 에이전트 고침·초안 저장·만약에 복사본 반영이 모두 여기로 승인 기준을 거친다.

차례: 계산 확인(store.schedules.run) → 바뀌는 것이 있는가 → 하네스 점검 → 승인 판단(app.agent.approval.assess)
→ 승인 건(store.approvals) → 승인이 필요하면 기다리고, 아니면 바로 반영(status auto, 되돌릴 버전 restore_to).
사유 = assess 사유 + extra_reasons, REASONS 차례·겹침 없음. Plan 다시 잡기 선택(reset_plan·plan_reset)은 없다 — Plan 은
계획 변경을 반영한 버전이 새로 찍는다(store.approvals._plan_change, PM 11-20 밤). 승인 표의 reset_plan 칸은 늘 False 다.
승인 수준: important = 사유가 하나라도 있으면 · all = 늘 · auto = condition_violated 가 있을 때. force_auto 면 늘 바로 반영.
다만 현장 관리자(Proposal.requested_role 'field')가 낸 것은 승인 수준·force_auto 와 상관없이 늘 승인을 기다린다.
쓰기는 flush 만 한다(commit·rollback 은 부르는 쪽). 분야 범위 내 규칙은 propose 를 거치지 않는다(Task 35).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from sqlalchemy.orm import Session

from app.agent.approval import REASONS, Assessment, _needs, assess
from app.agent.events import AgentEvent
from app.core.cpm import ScheduleError
from app.core.model import Schedule
from app.harness.assemble import assemble_all
from app.harness.checks import check
from app.harness.conditions import read_conditions
from app.store import approvals
from app.store.diff import schedule_changes
from app.store.messages import schedule_error_message
from app.store.scenarios import set_status
from app.store.schedules import from_json, load, run, to_json
from app.store.settings import approval_mode
from app.store.tables import Approval, Scenario
from app.store.versions import VersionConflict

STALE_MESSAGE = "그 사이 일정이 바뀌었습니다. 일정을 다시 읽고 고쳐 주세요."
NO_CHANGE_MESSAGE = "바뀌는 것이 없습니다."
USED_DRAFT_MESSAGE = "이미 저장한 초안입니다."
SCENARIO_STALE_MESSAGE = "기준 일정이 바뀌었습니다. 복사본을 다시 만들어 주세요."
SCENARIO_LOCKED_MESSAGE = "승인을 기다리거나 반영되었거나 버린 복사본은 낼 수 없습니다."
# 실적 날짜 규칙(재확인 2): 실제 시작·종료는 Data Date 뒤일 수 없고, 실제 시작은 착공일 앞일 수 없다.
ACTUALS_INVALID = "실제 날짜가 Data Date({})·착공일({})과 맞지 않아 넣을 수 없습니다: {}"
ACTUALS_BLOCKED = "실제 날짜가 Data Date({})와 맞지 않아 반영할 수 없습니다 — 현장에서 다시 올려 주세요. ({})"
FIELD_WAITS_NOTE = "현장 관리자가 올린 건이라 승인 수준과 상관없이 승인을 기다립니다 — 승인되기 전에는 일정이 바뀌지 않습니다."


@dataclass(frozen=True)
class Proposal:
    kind: Literal["first_save", "change"]
    title: str
    before: Schedule | None  # 첫 저장은 None
    before_conditions: list[dict]
    after: Schedule
    after_conditions: list[dict]
    schedule_id: int | None  # 첫 저장은 반영한 뒤에 생긴다
    draft_id: int | None
    base_version: int  # 첫 저장은 0
    # 낸 쪽: 'agent'(에이전트 도구) | 'user'(사람이 화면·API 로). 반영한 버전의 by_kind 가 되고, 'user' 가 바로 반영되면
    # 버전 작성자는 requested_by 다(승인으로 반영되면 승인한 사람). programs/conditions 의 확정과 같다.
    requested_kind: Literal["agent", "user"] = "agent"
    link_kind: Literal["scenario", "rule"] | None = None
    link_id: int | None = None
    rule_json: dict | None = None
    # 낸 사람의 역할. 'field'(현장 관리자)가 낸 것은 승인 수준·force_auto 와 상관없이 늘 승인을 기다린다(리뷰, F4).
    requested_role: str | None = None


@dataclass(frozen=True)
class ProposalResult:
    row: Approval
    applied: bool  # 바로 반영했는가(false 면 승인함에서 결정을 기다린다)
    reasons: list[str]


class ProposalError(Exception):
    """code: schedule_invalid(계산 안 됨) | no_change | stale(그 사이 버전이 바뀜) | draft_used |
    actual_dates(실적 날짜 규칙 위반, actual_dates_problem). message 는 한국어."""

    def __init__(self, code: Literal["schedule_invalid", "no_change", "stale", "draft_used", "actual_dates"],
                 message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ScenarioError(Exception):
    """복사본을 낼 수 없다. code: scenario_locked(open 이 아님) | scenario_stale(떠 온 버전이 지금 버전이 아님)."""

    def __init__(self, code: Literal["scenario_locked", "scenario_stale"], message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def actual_dates_problem(before: Schedule | None, after: Schedule) -> str | None:
    """바뀐(또는 새로 생긴) 실적 날짜 가운데 Data Date 뒤인 것(실제 시작·종료)과 착공일 앞인 것(실제 시작)을 한 줄로.
    없으면 None. 바뀌지 않은 실적은 보지 않는다(예전 자료 때문에 다른 변경까지 막지 않게)."""
    old = {a.id: a for a in before.activities} if before is not None else {}
    bad: list[str] = []
    for a in after.activities:
        o = old.get(a.id)
        for label, day, prev in (("실제 시작", a.actual_start, o.actual_start if o else None),
                                 ("실제 종료", a.actual_finish, o.actual_finish if o else None)):
            if day is None or day == prev:
                continue
            if after.data_date is not None and day > after.data_date:
                bad.append(f"{a.id} {label} {day.isoformat()} — Data Date 뒤")
            elif label == "실제 시작" and day < after.start:
                bad.append(f"{a.id} {label} {day.isoformat()} — 착공일 {after.start.isoformat()} 앞")
    if not bad:
        return None
    return ", ".join(bad[:3]) + (f" 외 {len(bad) - 3}건" if len(bad) > 3 else "")


def actuals_invalid(after: Schedule, problem: str) -> str:
    """일정 변경 길(propose·표 고치기·실적 도구)의 거절 글."""
    dd = after.data_date.isoformat() if after.data_date else "없음"
    return ACTUALS_INVALID.format(dd, after.start.isoformat(), problem)


def actuals_blocked(after: Schedule, problem: str) -> str:
    """현장 반영·승인 결정의 거절 글(현장에서 다시 올리라고)."""
    return ACTUALS_BLOCKED.format(after.data_date.isoformat() if after.data_date else "없음", problem)


def _effective(stored: list[dict]) -> dict[str, tuple]:
    """조립한 조건을 id → (종류, 값, 켜짐) 으로(차례·글·진 표시와 상관없이 비교하려고)."""
    return {c.id: (c.kind, c.params, c.enabled) for c in assemble_all(read_conditions(stored)[0])}


def unchanged(before: Schedule, before_conditions: list[dict], after: Schedule, after_conditions: list[dict]) -> bool:
    """일정(액티비티·선행)도 조건도 그대로인가."""
    return not schedule_changes(before, after) and _effective(before_conditions) == _effective(after_conditions)


def _assess(session: Session, p: Proposal) -> tuple[Assessment, list[dict], str]:
    """(사유를 더하기 전 판단, 변경 이력, 승인 수준). 계산이 안 되거나 바뀌는 것이 없거나 실적 날짜 규칙을 어기면 ProposalError."""
    if (problem := actual_dates_problem(p.before, p.after)) is not None:
        raise ProposalError("actual_dates", actuals_invalid(p.after, problem))
    try:
        run(p.after, p.after_conditions)  # 화면과 같은 계산이 되는지
    except ScheduleError as e:
        raise ProposalError("schedule_invalid", schedule_error_message(e)) from None
    changes = schedule_changes(p.before, p.after) if p.before is not None else []
    if p.before is not None and unchanged(p.before, p.before_conditions, p.after, p.after_conditions):
        raise ProposalError("no_change", NO_CHANGE_MESSAGE)
    conditions, unreadable = read_conditions(p.after_conditions)
    report = check(p.after, assemble_all(conditions))
    report = replace(report, invalid=unreadable + report.invalid)  # 읽지 못한 저장 조건도 센다(harness.check 와 같음)
    mode = approval_mode(session)
    return assess(p.before, p.after, p.before_conditions, p.after_conditions, report, mode=mode), changes, mode


def propose(session: Session, p: Proposal, *, chat_session_id: int | None, requested_by: str,
            emit: Callable[[AgentEvent], None] | None = None, force_auto: bool = False,
            extra_reasons: Sequence[str] = ()) -> ProposalResult:
    """승인 건을 만들고 승인이 필요하면 approval 사건을, 바로 반영하면 card auto_applied 사건을 낸다(emit 이 있을 때)."""
    emit = emit or (lambda _: None)
    result, changes, mode = _assess(session, p)
    found = {*result.decision.reasons, *extra_reasons}
    reasons = [r for r in REASONS if r in found]
    field = p.requested_role == "field"  # 현장 관리자가 낸 것은 늘 기다린다 — 승인함 요약(알릴 것)에 그렇게 적는다
    summary = {**result.summary, "notes": [FIELD_WAITS_NOTE]} if field else result.summary
    row = approvals.create(
        session, kind=p.kind, title=p.title, reasons_json=reasons, schedule_id=p.schedule_id, draft_id=p.draft_id,
        base_version=p.base_version, summary_json=summary, diff_json=result.diff, snapshot_json=to_json(p.after),
        conditions_json=p.after_conditions, changes_json=changes, status="pending",
        request=approvals.last_request(session, chat_session_id), chat_session_id=chat_session_id,
        requested_by=requested_by, requested_kind=p.requested_kind, link_kind=p.link_kind, link_id=p.link_id,
        rule_json=p.rule_json,
    )
    if field or (not force_auto and _needs(mode, reasons)):
        emit(AgentEvent("approval", {"id": row.id, "title": row.title, "reasons": list(row.reasons_json),
                                     "summary": row.summary_json}))
        return ProposalResult(row, False, reasons)
    try:
        approvals.apply(session, row, by_name=requested_by if p.requested_kind == "user" else approvals.AGENT_NAME)
    except VersionConflict:
        raise ProposalError("stale", STALE_MESSAGE) from None
    except approvals.DraftUsed:
        raise ProposalError("draft_used", USED_DRAFT_MESSAGE) from None
    row.status = "auto"
    row.restore_to = p.base_version if p.kind == "change" else None  # 첫 저장은 되돌릴 버전이 없다
    emit(AgentEvent("card", {"kind": "auto_applied", "schedule_id": row.schedule_id, "version": row.version,
                             "count": result.summary["changed_count"], "summary": row.summary_json}))
    return ProposalResult(row, True, reasons)


def submit_scenario(session: Session, scenario: Scenario, *, title: str | None, chat_session_id: int | None,
                    requested_by: str, requested_kind: Literal["agent", "user"] = "agent",
                    emit: Callable[[AgentEvent], None] | None = None) -> ProposalResult:
    """복사본을 지금 버전 위의 고침으로 낸다(link_kind 'scenario'). 승인 대기면 복사본은 submitted, 바로 반영이면
    store.links 가 applied 로 둔다. open 이 아니면·떠 온 버전이 지금 버전이 아니면 ScenarioError, 그 밖은 ProposalError.
    """
    before, stored, n = load(session, scenario.schedule_id)
    if scenario.status != "open":
        raise ScenarioError("scenario_locked", SCENARIO_LOCKED_MESSAGE)
    if scenario.base_version != n:
        raise ScenarioError("scenario_stale", SCENARIO_STALE_MESSAGE)
    p = Proposal(kind="change", title=title or scenario.name, before=before, before_conditions=stored,
                 after=from_json(scenario.snapshot_json), after_conditions=list(scenario.conditions_json),
                 schedule_id=scenario.schedule_id, draft_id=None, base_version=n, requested_kind=requested_kind,
                 link_kind="scenario", link_id=scenario.id)
    result = propose(session, p, chat_session_id=chat_session_id, requested_by=requested_by, emit=emit)
    if not result.applied:
        set_status(session, scenario, "submitted", approval_id=result.row.id)
    return result
