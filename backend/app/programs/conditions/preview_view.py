"""미리 보기 일정(저장하지 않은 조건으로 계산한 ScheduleView)과 움직인 액티비티.

ScheduleView 의 칸과 계산은 app.store.view.view_data 와 같다. view_data 는 저장된 버전만 읽으므로, 같은 모듈의
액티비티 줄 만들기(_activities)와 Plan 계산(_plan)을 그대로 써서 메모리의 일정으로 만든다(갈라지지 않게).
Plan 은 저장된 Plan 버전이다. 지금 버전이 Plan 이면 저장된(바꾸기 전) 계산이 Plan 이 된다.
"""

from sqlalchemy.orm import Session

from app.core.cpm import CpmResult
from app.core.model import Schedule
from app.store import view as store_view
from app.store.schedules import to_json
from app.store.tables import ScheduleRecord


def preview_view(session: Session, record: ScheduleRecord, schedule: Schedule, ready: Schedule,
                 cpm: CpmResult, n: int, saved: CpmResult) -> dict:
    """schedule = 저장된 일정, ready = 미리 볼 조건을 넣은 일정, cpm = 그 계산, saved = 저장된 조건으로 한 계산.

    version 은 기준 버전 n 그대로다(저장하지 않았다). 날짜는 date 객체(응답에서 'YYYY-MM-DD').
    """
    plan = store_view._plan(session, record.id, n, saved)
    activities = store_view._activities(schedule, ready.calendar, cpm, plan)
    snapshot = to_json(schedule)
    return {
        "id": record.id, "name": record.name, "domain": record.domain, "level": record.level, "version": n,
        "data_date": schedule.data_date, "finish": cpm.finish, "plan_finish": plan.finish if plan else None,
        "wbs": snapshot["wbs"], "activities": activities, "relations": snapshot["relations"],
        "resources": snapshot["resources"],
        "summary": {
            "critical_count": sum(a["critical"] for a in activities),
            "negative_float_count": sum(a["tf"] < 0 for a in activities),
            "warning_count": sum(a["status"].startswith("late") for a in activities),
        },
    }


def moved(schedule: Schedule, before: CpmResult, after: CpmResult) -> list[dict]:
    """시작이나 끝이 달라진 액티비티(일정 차례)."""
    rows = []
    for a in schedule.activities:
        b, c = before.rows[a.id], after.rows[a.id]
        if (b.es, b.ef) != (c.es, c.ef):
            rows.append({"activity_id": a.id, "name": a.name, "before": {"start": b.es, "finish": b.ef},
                         "after": {"start": c.es, "finish": c.ef}})
    return rows


def side(cpm: CpmResult, violated: int) -> dict:
    return {"finish": cpm.finish, "critical_count": sum(r.critical for r in cpm.rows.values()), "violated": violated}
