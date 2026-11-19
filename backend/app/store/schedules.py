"""일정 저장: JSON 바꾸기, 만들기, 읽기.

저장하는 것은 언제나 사용자가 만든 일정 그대로다. 자원 맞춤이 넣는 `pinned_start` 는
계산 중에만 쓰는 값이라 저장하지 않는다(`to_json` 이 빼고, `from_json` 은 None 으로 둔다).
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.model import (
    Activity,
    BlockedPeriod,
    CalendarSpec,
    Constraint,
    Relation,
    Resource,
    Schedule,
    WbsNode,
)
from app.store.tables import ScheduleRecord, ScheduleVersion


class NotFound(LookupError):
    """없는 일정이나 버전."""


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _day(s: str | None) -> date | None:
    return date.fromisoformat(s) if s is not None else None


def activity_json(a: Activity) -> dict:
    """액티비티 한 줄(pinned_start 는 넣지 않는다)."""
    return {
        "id": a.id,
        "name": a.name,
        "kind": a.kind,
        "wbs": a.wbs,
        "od": a.od,
        "rd": a.rd,
        "progress": a.progress,
        "actual_start": _iso(a.actual_start),
        "actual_finish": _iso(a.actual_finish),
        "constraint": (
            {"type": a.constraint.type, "date": a.constraint.date.isoformat()}
            if a.constraint
            else None
        ),
        "resources": list(a.resources),
        "tags": list(a.tags),
    }


def _calendar_json(c: CalendarSpec) -> dict:
    return {
        "days_per_week": c.days_per_week,
        "holidays": [d.isoformat() for d in c.holidays],
        "blocked": [
            {"start_md": list(p.start_md), "end_md": list(p.end_md), "tag": p.tag}
            for p in c.blocked
        ],
    }


def to_json(schedule: Schedule) -> dict:
    return {
        "start": schedule.start.isoformat(),
        "data_date": _iso(schedule.data_date),
        "calendar": _calendar_json(schedule.calendar),
        "wbs": [{"code": w.code, "name": w.name, "parent": w.parent} for w in schedule.wbs],
        "activities": [activity_json(a) for a in schedule.activities],
        "relations": [
            {"pred": r.pred, "succ": r.succ, "type": r.type, "lag": r.lag}
            for r in schedule.relations
        ],
        "resources": [
            {"id": r.id, "name": r.name, "unit": r.unit, "capacity": r.capacity}
            for r in schedule.resources
        ],
    }


def activity_from_json(d: dict) -> Activity:
    c = d["constraint"]
    return Activity(
        id=d["id"],
        name=d["name"],
        kind=d["kind"],
        wbs=d["wbs"],
        od=d["od"],
        rd=d["rd"],
        progress=d["progress"],
        actual_start=_day(d["actual_start"]),
        actual_finish=_day(d["actual_finish"]),
        constraint=Constraint(c["type"], date.fromisoformat(c["date"])) if c else None,
        resources=tuple(d["resources"]),
        tags=tuple(d["tags"]),
    )


def _calendar(d: dict) -> CalendarSpec:
    return CalendarSpec(
        days_per_week=d["days_per_week"],
        holidays=tuple(date.fromisoformat(h) for h in d["holidays"]),
        blocked=tuple(
            BlockedPeriod(tuple(p["start_md"]), tuple(p["end_md"]), p["tag"])
            for p in d["blocked"]
        ),
    )


def from_json(d: dict) -> Schedule:
    return Schedule(
        start=date.fromisoformat(d["start"]),
        calendar=_calendar(d["calendar"]),
        wbs=tuple(WbsNode(w["code"], w["name"], w["parent"]) for w in d["wbs"]),
        activities=tuple(activity_from_json(a) for a in d["activities"]),
        relations=tuple(Relation(r["pred"], r["succ"], r["type"], r["lag"]) for r in d["relations"]),
        resources=tuple(
            Resource(r["id"], r["name"], r["unit"], r["capacity"]) for r in d["resources"]
        ),
        data_date=_day(d["data_date"]),
    )


def create_schedule(
    session: Session,
    *,
    name: str,
    domain: str,
    level: str,
    schedule: Schedule,
    conditions: list[dict],
    by_kind: str,
    by_name: str,
    note: str,
) -> int:
    """일정과 버전 1을 만들고 일정 id 를 준다. 변경 이력은 남기지 않는다."""
    record = ScheduleRecord(
        name=name, domain=domain, level=level, current_version=1, created_by=by_name
    )
    session.add(record)
    session.flush()
    session.add(
        ScheduleVersion(
            schedule_id=record.id,
            n=1,
            snapshot_json=to_json(schedule),
            conditions_json=list(conditions),
            note=note,
            by_kind=by_kind,
            by_name=by_name,
        )
    )
    session.commit()
    return record.id


def get_record(session: Session, schedule_id: int) -> ScheduleRecord:
    record = session.get(ScheduleRecord, schedule_id)
    if record is None:
        raise NotFound(schedule_id)
    return record


def get_version(session: Session, schedule_id: int, n: int) -> ScheduleVersion:
    version = session.get(ScheduleVersion, (schedule_id, n))
    if version is None:
        raise NotFound((schedule_id, n))
    return version


def load(
    session: Session, schedule_id: int, version: int | None = None
) -> tuple[Schedule, list[dict], int]:
    """(일정, 조건 목록, 버전 번호). version 이 없으면 지금 버전. 없으면 NotFound."""
    n = version if version is not None else get_record(session, schedule_id).current_version
    row = get_version(session, schedule_id, n)
    return from_json(row.snapshot_json), list(row.conditions_json), n


def list_records(session: Session) -> list[ScheduleRecord]:
    return list(session.scalars(select(ScheduleRecord).order_by(ScheduleRecord.id)))


def plan_version(session: Session, schedule_id: int) -> int:
    """Plan 버전 번호: is_plan 인 것 가운데 가장 나중 것, 없으면 가장 앞 버전."""
    marked = session.scalar(
        select(ScheduleVersion.n)
        .where(ScheduleVersion.schedule_id == schedule_id, ScheduleVersion.is_plan)
        .order_by(ScheduleVersion.n.desc())
    )
    if marked is not None:
        return marked
    first = session.scalar(
        select(ScheduleVersion.n)
        .where(ScheduleVersion.schedule_id == schedule_id)
        .order_by(ScheduleVersion.n)
    )
    if first is None:
        raise NotFound(schedule_id)
    return first
