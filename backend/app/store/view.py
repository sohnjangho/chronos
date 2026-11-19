"""계산값을 담은 일정 자료 만들기 (일정 API 와 에이전트 도구가 같이 쓴다).

날짜·여유·주공정은 저장된 일정을 compute → level(shift=True) 한 결과(LevelResult.cpm)를 쓴다.
그래서 화면 날짜는 주요 자원 용량을 지킨다. Plan 값도 Plan 버전에 같은 계산을 한 것이다.
"""

from sqlalchemy.orm import Session

from app.core.calendar import WorkCalendar
from app.core.cpm import CpmResult, CpmRow, compute
from app.core.model import Activity, Schedule
from app.core.resources import level
from app.store.schedules import activity_json, get_record, load, plan_version, to_json


def run(schedule: Schedule) -> CpmResult:
    """경로 계산 뒤 자원 맞춤까지 한 결과. 깨진 일정이면 ScheduleError."""
    return level(schedule, compute(schedule), shift=True).cpm


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


def _activities(schedule: Schedule, cpm: CpmResult, plan: CpmResult) -> list[dict]:
    cal = WorkCalendar(schedule.calendar)
    weights = _weights(schedule)
    rows = []
    for a in schedule.activities:
        row, p = cpm.rows[a.id], plan.rows.get(a.id)
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


def view_data(session: Session, schedule_id: int) -> dict:
    """지금 버전의 계산 포함 자료(ScheduleView 의 칸 그대로). 계산한 날짜는 date 객체다.

    없는 일정이면 NotFound, 깨진 일정이면 ScheduleError.
    """
    record = get_record(session, schedule_id)
    schedule, _, n = load(session, schedule_id)
    cpm = run(schedule)
    plan_n = plan_version(session, schedule_id)
    plan = cpm if plan_n == n else run(load(session, schedule_id, plan_n)[0])
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
        "plan_finish": plan.finish,
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
