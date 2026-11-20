"""만약에 복사본 API: 목록·상세(지금 일정 대비 차이)·버리기·승인함으로 내기.

내기는 app.agent.proposals.submit_scenario(→ propose) 로 승인 기준을 거친다. 떠 온 버전이 지금 버전이 아니면 409
scenario_stale(사이의 고침을 덮지 않는다), open 이 아니면 409 scenario_locked. 승인 결과(반영·거부·충돌)가 복사본에
닿는 것은 store.links 가 한다.
"""

from collections.abc import Callable
from datetime import date

from sqlalchemy.orm import Session

from app.agent.approval import assess
from app.agent.proposals import (
    SCENARIO_STALE_MESSAGE,
    ProposalError,
    ScenarioError,
    submit_scenario,
)
from app.core.calendar import WorkCalendar
from app.core.cpm import ScheduleError
from app.errors import ApiError
from app.harness.assemble import prepare_stored
from app.harness.checks import CheckReport
from app.programs.scenarios.schemas import (
    DiscardOut,
    ScenarioDetail,
    ScenarioOut,
    StatusGroup,
    SubmitIn,
    SubmitOut,
)
from app.store import scenarios
from app.store.messages import schedule_error_message
from app.store.schedules import NotFound, from_json, get_record, load, run
from app.store.tables import Scenario, User

NOT_FOUND_MESSAGE = "복사본을 찾을 수 없습니다."
SCHEDULE_NOT_FOUND_MESSAGE = "일정을 찾을 수 없습니다."
DISCARD_LOCKED_MESSAGE = "승인을 기다리거나 반영된 복사본은 버릴 수 없습니다."
GROUPS = {"open": ("open", "submitted"), "applied": ("applied",), "all": ("open", "submitted", "applied", "discarded")}
_NO_REPORT = CheckReport(passed=[], violations=[], uncheckable=[])  # 차이(diff)만 쓴다


def _version(session: Session, schedule_id: int) -> int:
    try:
        return get_record(session, schedule_id).current_version
    except NotFound:
        raise ApiError(404, "not_found", SCHEDULE_NOT_FOUND_MESSAGE) from None


def _scenario(session: Session, schedule_id: int, scenario_id: int) -> Scenario:
    _version(session, schedule_id)
    try:
        row = scenarios.get(session, scenario_id)
    except scenarios.NotFound:
        row = None
    if row is None or row.schedule_id != schedule_id:
        raise ApiError(404, "not_found", NOT_FOUND_MESSAGE)
    return row


def _recovered(row: Scenario) -> bool:
    return row.status == "applied" and row.source == "shorten"


def _achieved(session: Session, schedule_id: int) -> Callable[[str], int | None]:
    """만들 때 기준 준공(ISO) → 지금 준공까지 당긴 근무일(지금 일정의 조건 넣은 달력). 지금 일정이 계산되지 않으면 None."""
    schedule, conditions, _ = load(session, schedule_id)
    try:
        finish = run(schedule, conditions).finish
    except ScheduleError:
        return lambda _: None
    cal = WorkCalendar(prepare_stored(schedule, conditions).calendar)
    return lambda base_finish: cal.workdays_between(finish, date.fromisoformat(base_finish))


def _out(row: Scenario, current: int, achieved: Callable[[str], int | None] | None = None) -> dict:
    s = row.summary_json
    recovery = None
    if achieved is not None and _recovered(row):
        base = s.get("base_finish")
        recovery = {"planned_gain": s.get("gain"), "achieved": achieved(base) if base else None}
    return {
        "id": row.id, "schedule_id": row.schedule_id, "name": row.name, "source": row.source,
        "base_version": row.base_version, "stale": row.base_version != current, "status": row.status,
        "approval_id": row.approval_id, "moves": row.moves_json, "delay_event_ids": row.delay_event_ids,
        "summary": s, "created_by": row.created_by, "created_at": row.created_at, "recovery": recovery,
    }


def list_scenarios(session: Session, schedule_id: int, status: StatusGroup) -> list[ScenarioOut]:
    current = _version(session, schedule_id)
    rows = scenarios.listed(session, schedule_id, GROUPS[status])
    achieved = _achieved(session, schedule_id) if any(_recovered(r) for r in rows) else None
    return [ScenarioOut(**_out(r, current, achieved)) for r in rows]


def detail(session: Session, schedule_id: int, scenario_id: int) -> ScenarioDetail:
    row = _scenario(session, schedule_id, scenario_id)
    before, stored, n = load(session, schedule_id)
    try:
        diff = assess(before, from_json(row.snapshot_json), stored, list(row.conditions_json), _NO_REPORT).diff
        achieved = _achieved(session, schedule_id) if _recovered(row) else None
    except ScheduleError as e:
        raise ApiError(422, "schedule_invalid", schedule_error_message(e)) from None
    return ScenarioDetail(**_out(row, n, achieved), diff=diff)


def discard(session: Session, schedule_id: int, scenario_id: int) -> DiscardOut:
    row = _scenario(session, schedule_id, scenario_id)
    if row.status in ("submitted", "applied"):
        raise ApiError(409, "scenario_locked", DISCARD_LOCKED_MESSAGE)
    scenarios.set_status(session, row, "discarded")
    session.commit()
    return DiscardOut(status="discarded")


def submit(session: Session, schedule_id: int, scenario_id: int, body: SubmitIn, user: User) -> SubmitOut:
    """확인 차례: 404 → 409 scenario_locked → 409 scenario_stale → 422 no_change·schedule_invalid → 승인 건."""
    row = _scenario(session, schedule_id, scenario_id)
    try:
        result = submit_scenario(session, row, title=body.title, chat_session_id=None, requested_by=user.name,
                                 requested_kind="user")  # 사람이 냈다: 버전 작성자는 사람(자동 반영이면 낸 사람)
    except ScenarioError as e:
        raise ApiError(409, e.code, e.message) from None
    except ProposalError as e:
        session.rollback()
        if e.code == "stale":  # 확인한 뒤 반영하는 사이에 일정이 바뀌었다
            raise ApiError(409, "scenario_stale", SCENARIO_STALE_MESSAGE) from None
        raise ApiError(409 if e.code == "draft_used" else 422, e.code, e.message) from None
    out = SubmitOut(approval_id=result.row.id, applied=result.applied, status=row.status)
    session.commit()
    return out
