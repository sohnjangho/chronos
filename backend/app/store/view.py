"""계산값을 담은 일정 자료 만들기 (일정 API 와 에이전트 도구가 같이 쓴다).

날짜·여유·주공정은 저장된 일정에 그 버전의 저장된 조건을 넣고(하네스 `prepare_stored`, 점검과 같은 준비)
compute → level(shift=True) 한 결과(LevelResult.cpm)를 쓴다. 그래서 화면 날짜는 주요 자원 용량과 조건을
지키고, 하네스 점검이 재는 일정과 같다. Plan 은 마지막 계획 변경 때의 예측(그때까지의 실적을 담은 같은 계산)을
고정한 것이다(버전 줄의 plan_json, PM 결정 11-20 밤 — store.versions). 그래서 실적·Data Date·기록한 지연은 Plan 을
옮기지 않고 상태(late +n)로만 보인다. plan_json 이 없는 옛 버전은 예전처럼 같은 버전의 일정에서 실적(실제 시작·종료·
진도·남은 기간)과 기록한 지연의 시작 하한(start_floor), Data Date 를 빼고 계산한다. 처음 계획(is_plan 버전)은 Plan 칸을
정하지 않는다.
액티비티·관계·자원 칸은 저장된 일정 그대로 보여 준다(조건이 넣은 FNLT·용량은 보이지 않는다).
달력(calendar)은 조건을 넣은 달력의 근무 요일과, 작업 금지 기간을 일정 기간 안의 날짜로 펼친 것이다.
가중치(weight)는 일정의 weight_mode(duration·manual)를 따른다.
표시 설정(display)은 그 일정 분야 묶음의 display(간트 묶음 기준·납기 이름·덧붙일 칸), 모르는 분야면 기본값이다.
"""

from calendar import isleap
from dataclasses import dataclass, replace
from datetime import date

from sqlalchemy.orm import Session

from app.core.calendar import WorkCalendar
from app.core.cpm import CpmResult, CpmRow, ScheduleError
from app.core.model import Activity, CalendarSpec, Schedule
from app.domains.loader import DisplaySpec, UnknownDomain, resolve_pack
from app.harness.assemble import prepare_stored
from app.store.schedules import (
    activity_json,
    get_record,
    get_version,
    load,
    run,
    to_json,
)

__all__ = ["Plan", "plan_changed", "plan_of", "plan_source", "plan_with", "run", "view_data", "view_of"]


@dataclass(frozen=True)
class PlanRow:
    es: date
    ef: date


@dataclass(frozen=True)
class Plan:
    """고정한 Plan(plan_json). 쓰는 쪽이 CpmResult 처럼 rows[id].es·ef 와 finish 만 읽는다."""

    rows: dict[str, PlanRow]
    finish: date

    @classmethod
    def from_json(cls, d: dict) -> "Plan":
        rows = {aid: PlanRow(date.fromisoformat(r["start"]), date.fromisoformat(r["finish"]))
                for aid, r in d["activities"].items()}
        return cls(rows, date.fromisoformat(d["finish"]))


def _status(cal: WorkCalendar, a: Activity, row: CpmRow, plan: CpmRow | PlanRow | None) -> str:
    if a.actual_finish is not None:
        return "done"
    if plan is None:
        return "new"
    diff = cal.workdays_between(plan.ef, row.ef, a.tags)
    if diff > 0:
        return f"late +{diff}"
    if diff < 0:
        return f"early {diff}"
    return "on_plan"


def _weights(schedule: Schedule, mode: str) -> dict[str, float]:
    """공정률 가중치(소수 4자리, 합 0 이면 모두 0).

    duration: 기간 비례, 마일스톤은 0. manual: manual_weight / (0 보다 큰 manual_weight 의 합), 없거나 0 이면 0.
    """
    if mode == "manual":
        own = {a.id: a.manual_weight or 0.0 for a in schedule.activities}
    else:
        own = {a.id: float(a.od) if a.kind == "task" else 0.0 for a in schedule.activities}
    total = sum(w for w in own.values() if w > 0)
    return {i: round(w / total, 4) if total and w > 0 else 0.0 for i, w in own.items()}


def _weight_missing(schedule: Schedule, mode: str) -> int:
    """manual 모드에서 가중치를 넣지 않은(None) task 수. duration 모드는 0."""
    if mode != "manual":
        return 0
    return sum(a.kind == "task" and a.manual_weight is None for a in schedule.activities)


def _on(year: int, month_day: tuple[int, int]) -> date:
    """그해의 그 월·일. 2월 29일이 없는 해는 2월 28일."""
    month, day = month_day
    if (month, day) == (2, 29) and not isleap(year):
        day = 28
    return date(year, month, day)


def _blocked(calendar: CalendarSpec, start: date, finish: date) -> list[dict]:
    """해마다 되풀이되는 작업 금지 기간을 날짜로 펼쳐 [start, finish] 와 겹치는 것만, 시작일 순.
    해를 넘기는 기간(start_md > end_md)은 끝이 다음 해다."""
    out = []
    for p in calendar.blocked:
        spill = 1 if p.start_md > p.end_md else 0  # 끝나는 해 - 시작하는 해
        for year in range(start.year - spill, finish.year + 1):
            first, last = _on(year, p.start_md), _on(year + spill, p.end_md)
            if first <= finish and last >= start:
                out.append({"tag": p.tag, "start": first, "finish": last})
    return sorted(out, key=lambda x: x["start"])


def _display(domain: str) -> dict:
    """그 분야 묶음의 표시 설정. 묶음이 없는 분야면 중립 기본값."""
    try:
        spec = resolve_pack(domain).display
    except UnknownDomain:
        spec = DisplaySpec(deadline_label="완료 기한")
    return spec.model_dump()


def _activities(
    schedule: Schedule, calendar: CalendarSpec, cpm: CpmResult, plan: CpmResult | Plan | None, mode: str
) -> list[dict]:
    """calendar 는 계산에 쓴 달력(조건을 넣은 것). 지연·앞섬 일수를 같은 달력으로 센다. mode = 가중치 방식."""
    cal = WorkCalendar(calendar)
    weights = _weights(schedule, mode)
    rows = []
    for a in schedule.activities:
        row, p = cpm.rows[a.id], plan.rows.get(a.id) if plan else None
        rows.append(
            {
                **activity_json(a),
                "es": row.es,
                "ef": row.ef,
                "ls": row.ls,
                "lf": row.lf,
                "plan_start": p.es if p else None,
                "plan_finish": p.ef if p else None,
                "tf": row.tf,
                "ff": row.ff,
                "critical": row.critical,
                "status": _status(cal, a, row, p),
                "weight": weights[a.id],
            }
        )
    return rows


def _without_actuals(schedule: Schedule) -> Schedule:
    """실적(실제 시작·종료·진도·남은 기간)·기록한 지연의 시작 하한(start_floor)·Data Date 를 뺀 일정."""
    acts = tuple(
        replace(a, actual_start=None, actual_finish=None, progress=0.0, rd=None, start_floor=None)
        for a in schedule.activities
    )
    return replace(schedule, activities=acts, data_date=None)


def plan_changed(before: Schedule, after: Schedule) -> bool:
    """계획 칸(기간·관계·제약·이름·종류·WBS·자원·꼬리표·달력 등)이 바뀌었는가(새 버전이 Plan 을 새로 찍는가).

    실적(실제 시작·종료·진도·남은 기간)·기록한 지연의 시작 하한·Data Date·가중치(manual_weight)만 바뀌었으면 False.
    """
    def plan_part(s: Schedule) -> Schedule:
        s = _without_actuals(s)
        return replace(s, activities=tuple(replace(a, manual_weight=None) for a in s.activities))

    return plan_part(before) != plan_part(after)


def plan_with(schedule: Schedule, conditions: list[dict], current: CpmResult | None) -> CpmResult | None:
    """옛 Plan(plan_json 이 없는 버전): 일정에서 실적·기록한 지연·Data Date 를 빼고, 저장 모양 조건을 넣어
    (prepare_stored) run 한 결과.

    current = 같은 일정을 같은 조건으로 계산한 것(없으면 None). 뺄 실적이 없으면 같은 계산이라 current 를
    그대로 쓴다. 계산이 안 되면 None(Plan 없음으로 본다).
    """
    planned = _without_actuals(schedule)
    if planned == schedule:
        return current
    try:
        return run(prepare_stored(planned, conditions))
    except ScheduleError:
        return None


def plan_of(session: Session, schedule_id: int, n: int, current: CpmResult | None) -> Plan | CpmResult | None:
    """버전 n 의 Plan: 고정한 plan_json. 없는 옛 버전이면 버전 n 의 일정과 조건으로 plan_with
    (current = 버전 n 을 그 버전의 조건으로 계산한 것)."""
    row = get_version(session, schedule_id, n)
    if row.plan_json is not None:
        return Plan.from_json(row.plan_json)
    schedule, conditions, _ = load(session, schedule_id, n)
    return plan_with(schedule, conditions, current)


def plan_source(session: Session, schedule_id: int, n: int) -> tuple[Schedule, list[dict], int]:
    """버전 n 의 Plan 을 계산으로 다시 만드는 (일정, 조건, 버전) — 비교판의 Plan 안.

    plan_json 이 있으면 Plan 을 찍은 버전의 내용 그대로(실적 포함 — 그 계산이 plan_json 이다),
    없는 옛 버전이면 버전 n 에서 실적을 뺀 것(plan_with 와 같은 계산).
    """
    plan = get_version(session, schedule_id, n).plan_json
    if plan is not None:
        return load(session, schedule_id, plan["version"])
    schedule, conditions, _ = load(session, schedule_id, n)
    return _without_actuals(schedule), conditions, n


def view_of(
    session: Session,
    schedule_id: int,
    n: int,
    schedule: Schedule,
    ready: Schedule,
    cpm: CpmResult,
    plan: CpmResult | Plan | None,
) -> dict:
    """메모리의 일정으로 만든 ScheduleView 자료(칸 그대로, 계산한 날짜는 date 객체). 저장된 것이 아니어도 된다.

    schedule = 저장 모양의 일정(액티비티·관계·자원 칸), ready = 조건을 넣은 일정(지연 일수를 세는 달력),
    cpm = ready 의 run 결과, plan = Plan(plan_of), n = 보일 버전 번호. 없는 일정이면 NotFound.
    """
    record = get_record(session, schedule_id)
    activities = _activities(schedule, ready.calendar, cpm, plan, record.weight_mode)
    snapshot = to_json(schedule)
    return {
        "id": record.id,
        "name": record.name,
        "domain": record.domain,
        "level": record.level,
        "version": n,
        "data_date": schedule.data_date,
        "finish": cpm.finish,
        "plan_finish": plan.finish if plan else None,
        "weight_mode": record.weight_mode,
        "display": _display(record.domain),
        "calendar": {
            "days_per_week": ready.calendar.days_per_week,
            "blocked": _blocked(ready.calendar, schedule.start, cpm.finish),
        },
        "wbs": snapshot["wbs"],
        "activities": activities,
        "relations": snapshot["relations"],
        "resources": snapshot["resources"],
        "summary": {
            "critical_count": sum(a["critical"] for a in activities),
            "negative_float_count": sum(a["tf"] < 0 for a in activities),
            "warning_count": sum(a["status"].startswith("late") for a in activities),
            "weight_missing": _weight_missing(schedule, record.weight_mode),
        },
    }


def view_data(
    session: Session, schedule_id: int, computed: tuple[int, CpmResult] | None = None
) -> dict:
    """지금 버전의 계산 포함 자료(ScheduleView 의 칸 그대로). 계산한 날짜는 date 객체다.

    computed=(버전 번호, 그 버전 일정의 run 결과) 를 주면, 지금 버전이 그 번호이고 저장된 조건이 일정을
    바꾸지 않을 때(조건을 넣은 계산과 넣지 않은 계산이 같을 때) 다시 계산하지 않는다. 조건이 일정을 바꾸면
    조건을 넣어 다시 계산한다. 일정 쓰기(`_write`)는 저장할 조건을 넣어 확인한 결과를 넘긴다.
    Plan 이 계산되지 않으면 plan 칸은 모두 None, status 는 "new" 다.
    없는 일정이면 NotFound, 지금 일정(조건을 넣은 것)이 깨졌으면 ScheduleError.
    """
    get_record(session, schedule_id)
    schedule, conditions, n = load(session, schedule_id)
    ready = prepare_stored(schedule, conditions)
    reuse = computed is not None and computed[0] == n and ready == schedule
    cpm = computed[1] if reuse else run(ready)
    return view_of(session, schedule_id, n, schedule, ready, cpm, plan_of(session, schedule_id, n, cpm))
