"""계산값을 담은 일정 자료 만들기 (일정 API 와 에이전트 도구가 같이 쓴다).

날짜·여유·주공정은 저장된 일정을 compute → level(shift=True) 한 결과(LevelResult.cpm)를 쓴다.
그래서 화면 날짜는 주요 자원 용량을 지킨다. Plan 값도 Plan 버전에 같은 계산을 한 것이다.
"""

from sqlalchemy.orm import Session

from app.core.calendar import WorkCalendar
from app.core.cpm import CpmResult, CpmRow, ScheduleError
from app.core.model import Activity, Schedule
from app.store.schedules import (
    activity_json,
    get_record,
    load,
    plan_version,
    run,
    to_json,
)

__all__ = ["run", "view_data"]


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


def _activities(schedule: Schedule, cpm: CpmResult, plan: CpmResult | None) -> list[dict]:
    cal = WorkCalendar(schedule.calendar)
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


def _plan(session: Session, schedule_id: int, n: int, cpm: CpmResult) -> CpmResult | None:
    """Plan 버전의 계산 결과. 계산이 안 되는 Plan 이면 None(Plan 없음으로 본다)."""
    plan_n = plan_version(session, schedule_id)
    if plan_n == n:
        return cpm
    try:
        return run(load(session, schedule_id, plan_n)[0])
    except ScheduleError:
        return None


def view_data(
    session: Session, schedule_id: int, computed: tuple[int, CpmResult] | None = None
) -> dict:
    """지금 버전의 계산 포함 자료(ScheduleView 의 칸 그대로). 계산한 날짜는 date 객체다.

    computed=(버전 번호, 그 버전의 run 결과) 를 주면, 지금 버전이 그 번호일 때 다시 계산하지 않는다.
    Plan 이 계산되지 않으면 plan 칸은 모두 None, status 는 "new" 다.
    없는 일정이면 NotFound, 지금 일정이 깨졌으면 ScheduleError.
    """
    record = get_record(session, schedule_id)
    schedule, _, n = load(session, schedule_id)
    cpm = computed[1] if computed is not None and computed[0] == n else run(schedule)
    plan = _plan(session, schedule_id, n, cpm)
    activities = _activities(schedule, cpm, plan)
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
