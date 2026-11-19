"""일정 저장: JSON 바꾸기, 만들기, 읽기.

저장하는 것은 언제나 사용자가 만든 일정 그대로다. 자원 맞춤이 넣는 `pinned_start` 는
계산 중에만 쓰는 값이라 저장하지 않는다(`to_json` 이 빼고, `from_json` 은 None 으로 둔다).
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cpm import CpmResult, compute
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
from app.core.resources import level as level_schedule
from app.harness.assemble import prepare_stored
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
    """기본값이 있는 칸은 없어도 읽는다(그 칸이 생기기 전에 저장한 스냅숏)."""
    c = d.get("constraint")
    return Activity(
        id=d["id"],
        name=d["name"],
        kind=d["kind"],
        wbs=d["wbs"],
        od=d["od"],
        rd=d.get("rd"),
        progress=d.get("progress", 0.0),
        actual_start=_day(d.get("actual_start")),
        actual_finish=_day(d.get("actual_finish")),
        constraint=Constraint(c["type"], date.fromisoformat(c["date"])) if c else None,
        resources=tuple(d.get("resources", ())),
        tags=tuple(d.get("tags", ())),
    )


def _calendar(d: dict) -> CalendarSpec:
    return CalendarSpec(
        days_per_week=d["days_per_week"],
        holidays=tuple(date.fromisoformat(h) for h in d.get("holidays", ())),
        blocked=tuple(
            BlockedPeriod(tuple(p["start_md"]), tuple(p["end_md"]), p["tag"])
            for p in d.get("blocked", ())
        ),
    )


def from_json(d: dict) -> Schedule:
    return Schedule(
        start=date.fromisoformat(d["start"]),
        calendar=_calendar(d["calendar"]),
        wbs=tuple(WbsNode(w["code"], w["name"], w["parent"]) for w in d["wbs"]),
        activities=tuple(activity_from_json(a) for a in d["activities"]),
        relations=tuple(
            Relation(r["pred"], r["succ"], r.get("type", "FS"), r.get("lag", 0))
            for r in d["relations"]
        ),
        resources=tuple(
            Resource(r["id"], r["name"], r["unit"], r["capacity"]) for r in d.get("resources", ())
        ),
        data_date=_day(d.get("data_date")),
    )


def run(schedule: Schedule, conditions: list[dict] | None = None) -> CpmResult:
    """경로 계산 뒤 자원 맞춤까지 한 결과(화면 날짜). 깨진 일정이면 ScheduleError.

    conditions(저장된 조건 dict 목록)를 주면 하네스 점검과 같은 준비(`app.harness.assemble.prepare`:
    기본 규칙과 조립, 켜진 조건 넣기)를 한 일정을 계산한다. 읽지 못하는 조건 dict 는 건너뛴다.
    """
    if conditions is not None:
        schedule = prepare_stored(schedule, conditions)
    return level_schedule(schedule, compute(schedule), shift=True).cpm


def end_write(session: Session, commit: bool) -> None:
    """commit 이면 커밋, 아니면 flush 만 한다(트랜잭션은 부른 쪽이 끝낸다)."""
    if commit:
        session.commit()
    else:
        session.flush()


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
    commit: bool = True,
) -> int:
    """일정과 버전 1을 만들고 일정 id 를 준다. 변경 이력은 남기지 않는다.

    먼저 저장할 조건을 넣어 계산해 본다(화면과 같은 계산). 깨진 일정이면 ScheduleError 를 내고
    아무것도 저장하지 않는다.
    """
    run(schedule, conditions)
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
    end_write(session, commit)
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
