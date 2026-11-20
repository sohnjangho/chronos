"""미리 보기 응답의 조각: 움직인 액티비티와 before/after 요약.

미리 보기 일정(ScheduleView)은 app.store.view.view_of 가 만든다(view_data 와 같은 함수).
"""

from app.core.cpm import CpmResult
from app.core.model import Schedule


def moved(schedule: Schedule, before: CpmResult, after: CpmResult) -> list[dict]:
    """시작이나 끝이 달라진 액티비티(일정 차례)."""
    rows = []
    for a in schedule.activities:
        b, c = before.rows[a.id], after.rows[a.id]
        if (b.es, b.ef) != (c.es, c.ef):
            rows.append({"activity_id": a.id, "name": a.name, "before": {"start": b.es, "finish": b.ef},
                         "after": {"start": c.es, "finish": c.ef}})
    return rows


def side(cpm: CpmResult | None, violated: int) -> dict:
    """준공·크리티컬 수·위반 수. 계산이 안 되는 일정(cpm None)이면 준공·크리티컬 수는 None."""
    if cpm is None:
        return {"finish": None, "critical_count": None, "violated": violated}
    return {"finish": cpm.finish, "critical_count": sum(r.critical for r in cpm.rows.values()), "violated": violated}
