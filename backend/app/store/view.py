"""계산값을 담은 일정 자료 만들기 (일정 API 와 에이전트 도구가 같이 쓴다).

날짜·여유·주공정은 저장된 일정에 그 버전의 저장된 조건을 넣고(하네스 `prepare_stored`, 점검과 같은 준비)
compute → level(shift=True) 한 결과(LevelResult.cpm)를 쓴다. 그래서 화면 날짜는 주요 자원 용량과 조건을
지키고, 하네스 점검이 재는 일정과 같다. Plan 값도 Plan 버전(그 버전의 조건)에 같은 계산을 한 것이다.
액티비티·관계·자원 칸은 저장된 일정 그대로 보여 준다(조건이 넣은 FNLT·용량은 보이지 않는다).
"""

from sqlalchemy.orm import Session

from app.core.calendar import WorkCalendar
from app.core.cpm import CpmResult, CpmRow, ScheduleError
from app.core.model import Activity, CalendarSpec, Schedule
from app.harness.assemble import prepare_stored
from app.store.schedules import (
    activity_json,
    get_record,
    load,
    plan_version,
    run,
    to_json,
)

__all__ = ["plan_of", "run", "view_data", "view_of"]


def _status(cal: WorkCalendar, a: Activity, row: CpmRow, plan: CpmRow | None) -> str:
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


def _weights(schedule: Schedule) -> dict[str, float]:
    """기간 비례 가중치. 마일스톤은 0, 기간 합이 0 이면 모두 0."""
    total = sum(a.od for a in schedule.activities if a.kind == "task")
    return {
        a.id: round(a.od / total, 4) if total and a.kind == "task" else 0.0
        for a in schedule.activities
    }


def _activities(
    schedule: Schedule, calendar: CalendarSpec, cpm: CpmResult, plan: CpmResult | None
) -> list[dict]:
    """calendar 는 계산에 쓴 달력(조건을 넣은 것). 지연·앞섬 일수를 같은 달력으로 센다."""
    cal = WorkCalendar(calendar)
    weights = _weights(schedule)
    rows = []
    for a in schedule.activities:
        row, p = cpm.rows[a.id], plan.rows.get(a.id) if plan else None
        rows.append(
            {
                **activity_json(a),
                "es": row.es,
                "ef": row.ef,
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


def plan_of(session: Session, schedule_id: int, n: int, current: CpmResult | None) -> CpmResult | None:
    """Plan 버전의 계산 결과. Plan 이 버전 n 이면 current(버전 n 의 계산, 없으면 None).
    그 밖에는 Plan 버전을 그 버전의 조건으로 계산한다. 계산이 안 되는 Plan 이면 None(Plan 없음으로 본다).
    """
    plan_n = plan_version(session, schedule_id)
    if plan_n == n:
        return current
    schedule, conditions, _ = load(session, schedule_id, plan_n)
    try:
        return run(prepare_stored(schedule, conditions))
    except ScheduleError:
        return None


def view_of(
    session: Session,
    schedule_id: int,
    n: int,
    schedule: Schedule,
    ready: Schedule,
    cpm: CpmResult,
    plan: CpmResult | None,
) -> dict:
    """메모리의 일정으로 만든 ScheduleView 자료(칸 그대로, 계산한 날짜는 date 객체). 저장된 것이 아니어도 된다.

    schedule = 저장 모양의 일정(액티비티·관계·자원 칸), ready = 조건을 넣은 일정(지연 일수를 세는 달력),
    cpm = ready 의 run 결과, plan = Plan 계산(plan_of), n = 보일 버전 번호. 없는 일정이면 NotFound.
    """
    record = get_record(session, schedule_id)
    activities = _activities(schedule, ready.calendar, cpm, plan)
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
        "wbs": snapshot["wbs"],
        "activities": activities,
        "relations": snapshot["relations"],
        "resources": snapshot["resources"],
        "summary": {
            "critical_count": sum(a["critical"] for a in activities),
            "negative_float_count": sum(a["tf"] < 0 for a in activities),
            "warning_count": sum(a["status"].startswith("late") for a in activities),
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
