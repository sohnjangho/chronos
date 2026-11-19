"""core 시험이 같이 쓰는 일정 만들기 도우미."""

from datetime import date

from app.core.model import Activity, CalendarSpec, Schedule, WbsNode

CAL5 = CalendarSpec(days_per_week=5)


def act(i, od, **k):
    return Activity(id=i, name=i, kind="task", wbs="1", od=od, **k)


def sched(acts, rels, cal=CAL5, start=date(2027, 3, 1)):
    return Schedule(
        start=start,
        calendar=cal,
        wbs=(WbsNode("1", "w", None),),
        activities=tuple(acts),
        relations=tuple(rels),
    )
