"""store·programs 시험이 같이 쓰는 일정 만들기 도우미."""

from datetime import date

from app.core.model import Activity, CalendarSpec, Relation, Resource, Schedule, WbsNode
from app.store.schedules import create_schedule

CAL5 = CalendarSpec(days_per_week=5)


def task(i: str, od: int, **k) -> Activity:
    return Activity(**{"id": i, "name": f"작업 {i}", "kind": "task", "wbs": "1", "od": od, **k})


def make(acts, rels=(), resources=(), cal=CAL5) -> Schedule:
    return Schedule(
        start=date(2027, 3, 1),
        calendar=cal,
        wbs=(WbsNode("1", "골조", None),),
        activities=tuple(acts),
        relations=tuple(rels),
        resources=tuple(resources),
    )


def sample() -> Schedule:
    return make(
        [task("A", 3), task("B", 2)],
        [Relation("A", "B")],
        [Resource("crane", "타워크레인", "대", 1)],
    )


def store(session, schedule: Schedule, conditions: list[dict] | None = None) -> int:
    return create_schedule(
        session,
        name="시험 일정",
        domain="construction",
        level="L3",
        schedule=schedule,
        conditions=conditions or [],
        by_kind="agent",
        by_name="에이전트",
        note="처음 만듦",
    )
