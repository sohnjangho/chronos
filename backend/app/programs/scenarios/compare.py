"""비교판 자료: 두 안의 요약(SideOut)·액티비티별 차이(RowOut), 여러 안 요약 표.

안(ref): `current`(지금 버전) · `plan`(지금 버전의 Plan 을 찍은 버전의 내용 그대로 — 그 계산이 고정한 Plan 이다,
store.view.plan_source, PM 결정 11-20 밤. 옛 버전이면 지금 버전을 실적·기록한 지연 없이) · `v:<n>`(버전 n) ·
`s:<복사본 id>`(그 일정의 복사본). 모르는 ref 는 422 invalid_ref.
날짜는 모두 저장 모양의 일정에 그 안의 저장 조건을 넣고(prepare_stored) compute → level(shift=True) 한 값이다(화면과 같다).
- 안 요약: plan_delta = Plan 준공 → 이 안 준공(Plan 이 계산되지 않으면 None — 그때 plan ref 만 422, 요약 표는 Plan 을 뺌),
  deadline = 켜진 finish_by 가운데 가장 이른 기한(ISO, 없으면 None), deadline_float = 이 안 준공 → 그 기한
  (없으면 None, 늦으면 음수). 차이는 모두 이 안의 조건 넣은 달력의 근무일. violations·uncheckable 은 하네스 점검의 개수,
  peak 는 store.scenarios 요약과 같은 자원 최고 부하. changes: 복사본은 이동 글, 버전은 그 버전의 note.
- 줄: 기준 차례, 다음 비교에만 있는 것. 차이는 기준 쪽 달력(그 액티비티의 꼬리표)의 근무일로 other − base.
계산이 안 되는 안이 있으면 422 schedule_invalid(detail = ScheduleError.detail).
"""

import re
from datetime import date

from sqlalchemy.orm import Session

from app.core.calendar import WorkCalendar
from app.core.cpm import ScheduleError, compute
from app.core.model import Activity, Schedule
from app.core.resources import LevelResult, level
from app.errors import ApiError
from app.harness.assemble import assemble_all, prepare_stored
from app.harness.checks import check
from app.harness.conditions import Condition, condition_problem, read_conditions
from app.store import scenarios
from app.store.messages import schedule_error_message
from app.store.scenarios import _peak  # 복사본 요약과 같은 자원 최고 부하
from app.store.schedules import NotFound, from_json, get_record, get_version, load
from app.store.view import plan_source

INVALID_REF_MESSAGE = "비교할 안을 찾을 수 없습니다: {}"
SCHEDULE_NOT_FOUND_MESSAGE = "일정을 찾을 수 없습니다."
SUMMARY_STATUSES = ("open", "submitted")
_REF = re.compile(r"current|plan|v:[1-9]\d{0,9}|s:[1-9]\d{0,9}")


def earliest_due(assembled: list[Condition]) -> date | None:
    """켜진(형식이 맞는) finish_by 가운데 가장 이른 기한."""
    dues = [date.fromisoformat(c.params["date"]) for c in assembled
            if condition_problem(c) is None and c.enabled and c.kind == "finish_by"]
    return min(dues) if dues else None


def change_of(base: dict | None, other: dict | None, start_delta: int | None, finish_delta: int | None) -> str:
    """줄의 구분: 한쪽에만 있으면 added·removed, 끝(같으면 시작)이 당겨지면 pulled·밀리면 pushed,
    날짜가 같고 기간만 다르면 duration, 아니면 same."""
    if other is None:
        return "removed"
    if base is None:
        return "added"
    moved = finish_delta or start_delta
    if moved:
        return "pulled" if moved < 0 else "pushed"
    return "duration" if base["od"] != other["od"] else "same"


class _Side:
    """한 안: 저장 모양의 일정·조건과 보일 칸. 계산(ready·lv)은 compute() 뒤에 있다."""

    def __init__(self, ref: str, label: str, version: int, schedule: Schedule, conditions: list[dict], *,
                 changes: list[str], stale: bool = False, status: str | None = None) -> None:
        self.ref, self.label, self.version = ref, label, version
        self.schedule, self.conditions = schedule, conditions
        self.changes, self.stale, self.status = changes, stale, status
        self.ready: Schedule | None = None
        self.lv: LevelResult | None = None

    def compute(self) -> None:
        if self.lv is None:
            self.ready = prepare_stored(self.schedule, self.conditions)
            self.lv = level(self.ready, compute(self.ready), shift=True)


class _Board:
    """한 일정의 안들을 ref 로 찾아 한 번만 계산한다."""

    def __init__(self, session: Session, schedule_id: int) -> None:
        try:
            get_record(session, schedule_id)
        except NotFound:
            raise ApiError(404, "not_found", SCHEDULE_NOT_FOUND_MESSAGE) from None
        self.session, self.schedule_id = session, schedule_id
        self.current = load(session, schedule_id)
        self._sides: dict[str, _Side] = {}
        self._plan: tuple[date | None] | None = None  # (Plan 준공 또는 계산 안 됨 None,) — 한 번만 센다

    def plan_finish(self) -> date | None:
        """Plan 준공. 계산이 안 되면 None(plan_of 처럼 Plan 없음으로 본다)."""
        if self._plan is None:
            try:
                plan = self.side("plan")
                plan.compute()
                self._plan = (plan.lv.finish,)
            except ScheduleError:
                self._plan = (None,)
        return self._plan[0]

    def side(self, ref: str) -> _Side:
        """ref 의 안(계산 전). 모르는 ref 면 422 invalid_ref."""
        if ref not in self._sides:
            self._sides[ref] = self._find(ref)
        return self._sides[ref]

    def _find(self, ref: str) -> _Side:
        if _REF.fullmatch(ref) is None:
            raise _invalid(ref)
        schedule, conditions, n = self.current
        if ref == "current":
            return _Side(ref, f"현재 일정 (버전 {n})", n, schedule, conditions, changes=[])
        if ref == "plan":
            planned, planned_conditions, at = plan_source(self.session, self.schedule_id, n)
            return _Side(ref, f"Plan (버전 {at})", at, planned, planned_conditions, changes=[])
        number = int(ref[2:])
        if ref.startswith("v:"):
            try:
                row = get_version(self.session, self.schedule_id, number)
            except NotFound:
                raise _invalid(ref) from None
            return _Side(ref, f"버전 {number}", number, from_json(row.snapshot_json), list(row.conditions_json),
                         changes=[row.note] if row.note else [])
        try:
            sc = scenarios.get(self.session, number)
        except scenarios.NotFound:
            raise _invalid(ref) from None
        if sc.schedule_id != self.schedule_id:
            raise _invalid(ref)
        return _Side(ref, sc.name, sc.base_version, from_json(sc.snapshot_json), list(sc.conditions_json),
                     changes=[m["text"] for m in sc.moves_json], stale=sc.base_version != n, status=sc.status)

    def out(self, ref: str) -> dict:
        """안 요약(SideOut). 이 안이 계산되지 않으면 ScheduleError(Plan 이 계산되지 않으면 plan_delta 만 None)."""
        side = self.side(ref)
        side.compute()
        plan_finish = self.plan_finish()
        cal = WorkCalendar(side.ready.calendar)
        assembled = assemble_all(read_conditions(side.conditions)[0])
        report = check(side.schedule, assembled)
        due, finish = earliest_due(assembled), side.lv.finish
        return {
            "ref": side.ref, "label": side.label, "version": side.version, "finish": finish.isoformat(),
            "plan_delta": cal.workdays_between(plan_finish, finish) if plan_finish else None,
            "deadline": due.isoformat() if due else None,
            "deadline_float": cal.workdays_between(finish, due) if due else None,
            "critical_count": sum(row.critical for row in side.lv.cpm.rows.values()),
            "violations": len(report.violations), "uncheckable": len(report.uncheckable),
            "peak": _peak(side.schedule, side.lv), "changes": side.changes, "stale": side.stale,
            "status": side.status,
        }


def _invalid(ref: str) -> ApiError:
    return ApiError(422, "invalid_ref", INVALID_REF_MESSAGE.format(ref))


def _cell(side: _Side, a: Activity | None) -> dict | None:
    if a is None:
        return None
    row = side.lv.cpm.rows[a.id]
    return {"start": row.es.isoformat(), "finish": row.ef.isoformat(), "od": a.od}


def _rows(base: _Side, other: _Side) -> list[dict]:
    """액티비티별 차이: 기준 차례, 다음 비교에만 있는 것. 차이는 기준 쪽 달력의 근무일(other − base)."""
    cal = WorkCalendar(base.ready.calendar)
    mine = {a.id: a for a in base.schedule.activities}
    theirs = {a.id: a for a in other.schedule.activities}
    order = [*mine, *(i for i in theirs if i not in mine)]
    rows = []
    for i in order:
        a, o = mine.get(i), theirs.get(i)
        b_cell, o_cell = _cell(base, a), _cell(other, o)
        start_delta = finish_delta = None
        if a is not None and o is not None:
            b_row, o_row = base.lv.cpm.rows[i], other.lv.cpm.rows[i]
            start_delta = cal.workdays_between(b_row.es, o_row.es, a.tags)
            finish_delta = cal.workdays_between(b_row.ef, o_row.ef, a.tags)
        shown = a or o
        rows.append({
            "activity_id": i, "name": shown.name, "wbs": shown.wbs, "base": b_cell, "other": o_cell,
            "start_delta": start_delta, "finish_delta": finish_delta,
            "change": change_of(b_cell, o_cell, start_delta, finish_delta),
        })
    return rows


def _explained(error: ScheduleError) -> ApiError:
    return ApiError(422, "schedule_invalid", schedule_error_message(error), error.detail)


def compare(session: Session, schedule_id: int, base_ref: str, other_ref: str) -> dict:
    """두 안의 비교: {base, other, rows, changed_count}. 확인 차례: 404 → ref 422 → 계산 422."""
    board = _Board(session, schedule_id)
    base, other = board.side(base_ref), board.side(other_ref)
    try:
        out = {"base": board.out(base_ref), "other": board.out(other_ref)}
        rows = _rows(base, other)
    except ScheduleError as e:
        raise _explained(e) from None
    return {**out, "rows": rows, "changed_count": sum(r["change"] != "same" for r in rows)}


def summary(session: Session, schedule_id: int) -> dict:
    """여러 안 요약 표: 현재 · Plan(계산되면) · 열린(open·submitted) 복사본 새것부터."""
    board = _Board(session, schedule_id)
    opened = [f"s:{row.id}" for row in scenarios.listed(session, schedule_id, SUMMARY_STATUSES)]
    try:
        current = board.out("current")
        plan = [board.out("plan")] if board.plan_finish() is not None else []
        return {"sides": [current, *plan, *(board.out(ref) for ref in opened)]}
    except ScheduleError as e:
        raise _explained(e) from None
