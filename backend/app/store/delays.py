"""지연 사건(delay_events): 적기·읽기·고치기, core 모양으로 바꾸기, 반영 표시, 열린 사건을 넣은 기준 일정, 영향 분석.

사건은 'open'(아직 일정에 없음) → 'reflected'(그 버전에 들어감) 두 상태라 두 번 세지 않는다. 열린 사건만 일정에 넣는다.
기록한 지연은 저장된 일정도 Plan 도 바꾸지 않는다(PM 결정 11-20). 반영은 지연 반영안(복사본)을 승인할 때만이다.

영향 분석(`refresh`): 지금 버전을 `prepare_stored` 한 일정에 열린 사건을 `core.delay.analyze` 로 차례로 넣어 사건마다
그 몫의 영향을 `impact_json` 에 적고 `analyzed_version` 을 단다. 반영된 사건은 다시 넣지 않고 적어 둔 영향을 그대로 쓴다.
`report` 는 API(`DelaysOut`)와 도구가 같이 쓰는 묶음 자료다(store.view.view_data 처럼).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import delay as core_delay
from app.core.calendar import WorkCalendar
from app.core.model import Schedule
from app.harness.assemble import assemble_all, prepare_stored
from app.harness.conditions import condition_problem, read_conditions
from app.store.schedules import NotFound, load, run
from app.store.tables import DelayEvent as DelayEventRow
from app.store.view import plan_of

__all__ = [
    "RESPONSIBILITIES", "DelayEventRow", "DelayedBase", "NotFound", "create", "delayed_base", "delete", "get",
    "impact_json", "listed", "mark_reflected", "open_events", "refresh", "report", "save_impacts", "to_core", "update",
]

RESPONSIBILITIES = ("owner", "ours", "force", "undecided")  # 발주처·우리·불가항력·정하지 않음


def open_events(session: Session, schedule_id: int) -> list[DelayEventRow]:
    """그 일정의 열린 사건, (발생일, id) 순."""
    query = (
        select(DelayEventRow)
        .where(DelayEventRow.schedule_id == schedule_id, DelayEventRow.status == "open")
        .order_by(DelayEventRow.start_date, DelayEventRow.id)
    )
    return list(session.scalars(query))


def to_core(row: DelayEventRow) -> core_delay.DelayEvent:
    return core_delay.DelayEvent(str(row.id), row.activity_id, row.start_date, row.days, row.daily_cost)


def mark_reflected(session: Session, ids: Sequence[int], version: int) -> None:
    """열린 사건을 그 버전에 반영된 것으로 둔다(이미 반영된 사건은 그대로). flush 만."""
    if not ids:
        return
    query = select(DelayEventRow).where(DelayEventRow.id.in_(list(ids)), DelayEventRow.status == "open")
    for row in session.scalars(query):
        row.status, row.reflected_version = "reflected", version
    session.flush()


@dataclass(frozen=True)
class DelayedBase:
    schedule: Schedule  # 지금 버전 원본(조건을 넣지 않은 저장 모양)에 열린 사건을 넣은 것
    conditions: list[dict]  # 지금 버전의 저장 조건 그대로
    version: int  # 떠 온 버전
    event_ids: list[int]  # 넣은 사건(넣은 차례)
    skipped: list[int]  # 넣지 못한 사건: 끝난 액티비티·마일스톤·없는 액티비티


def delayed_base(session: Session, schedule_id: int, event_ids: Sequence[int] | None = None) -> DelayedBase:
    """지금 버전 원본에 열린 사건(event_ids 를 주면 그 가운데 열린 것만)을 (발생일, id) 차례로 넣는다.

    하한·남은 기간은 사용자가 보는 일정(저장 조건을 넣은 일정)에서 `core.delay.insert_delay` 로 정하고, 그 액티비티의
    `start_floor`·`rd` 만 원본에 옮긴다(조건이 이 두 칸을 바꾸지 않으므로 원본 + 조건 = 조건 넣은 일정 + 사건).
    없는 일정이면 NotFound.
    """
    schedule, conditions, n = load(session, schedule_id)
    wanted = None if event_ids is None else set(event_ids)
    rows = [r for r in open_events(session, schedule_id) if wanted is None or r.id in wanted]
    by_id = {str(r.id): r.id for r in rows}
    inserted, skipped = [], []
    for event in core_delay.ordered(to_core(r) for r in rows):
        try:
            ready, note = core_delay.insert_delay(prepare_stored(schedule, conditions), event)
        except core_delay.DelayInputError:  # 사건을 적은 뒤 액티비티가 지워졌다
            note = "missing"
        if note is not None:
            skipped.append(by_id[event.id])
            continue
        moved = next(a for a in ready.activities if a.id == event.activity_id)
        acts = tuple(replace(a, start_floor=moved.start_floor, rd=moved.rd) if a.id == moved.id else a
                     for a in schedule.activities)
        schedule = replace(schedule, activities=acts)
        inserted.append(by_id[event.id])
    return DelayedBase(schedule, conditions, n, inserted, skipped)


# ── 적기·읽기·고치기 ────────────────────────────────────────────────────


def create(
    session: Session,
    *,
    schedule_id: int,
    activity_id: str,
    start_date: date,
    days: int,
    cause: str,
    responsibility: str,
    daily_cost: int | None,
    evidence: str,
    source: str,
    created_by: str,
    status: str = "open",
) -> DelayEventRow:
    """사건 한 줄을 넣고 flush 한다. 영향은 비어 있다(refresh 나 부른 쪽이 채운다)."""
    row = DelayEventRow(
        schedule_id=schedule_id, activity_id=activity_id, start_date=start_date, days=days, cause=cause,
        responsibility=responsibility, daily_cost=daily_cost, evidence=evidence, source=source, status=status,
        impact_json={}, created_by=created_by,
    )
    session.add(row)
    session.flush()
    return row


def get(session: Session, eid: int) -> DelayEventRow:
    """없으면 NotFound."""
    row = session.get(DelayEventRow, eid)
    if row is None:
        raise NotFound(eid)
    return row


def update(session: Session, row: DelayEventRow, **fields) -> None:
    """칸을 바꾼다(확인은 부른 쪽). flush 만."""
    for name, value in fields.items():
        setattr(row, name, value)
    session.flush()


def delete(session: Session, row: DelayEventRow) -> None:
    session.delete(row)
    session.flush()


def listed(session: Session, schedule_id: int) -> list[DelayEventRow]:
    """그 일정의 모든 사건(열림·반영), (발생일, id) 순."""
    query = (
        select(DelayEventRow)
        .where(DelayEventRow.schedule_id == schedule_id)
        .order_by(DelayEventRow.start_date, DelayEventRow.id)
    )
    return list(session.scalars(query))


# ── 영향 분석 ─────────────────────────────────────────────────────────


def impact_json(i: core_delay.EventImpact) -> dict:
    """EventImpact → 저장 모양(날짜는 ISO). 이름은 적지 않는다(보일 때 지금 일정에서 붙인다)."""
    return {
        "applied": i.applied, "note": i.note, "finish_before": i.finish_before.isoformat(),
        "finish_after": i.finish_after.isoformat(), "finish_delta": i.finish_delta, "absorbed": i.absorbed,
        "milestones": [{"activity_id": m.activity_id, "before": m.before.isoformat(), "after": m.after.isoformat(),
                        "delta": m.delta} for m in i.milestones],
        "critical_added": list(i.critical_added), "critical_removed": list(i.critical_removed),
        "affected": list(i.affected),
        "new_clashes": [{"resource_id": c.resource_id, "first": c.first.isoformat(), "days": c.days, "over": c.over}
                        for c in i.new_clashes],
        "cost": i.cost,
    }


def _missing(row: DelayEventRow, finish: date) -> dict:
    """넣을 수 없는 사건(사건을 적은 뒤 액티비티가 지워짐)의 영향: 넣지 않음, 몫 0."""
    day = finish.isoformat()
    return {"applied": False, "note": f"없는 액티비티입니다: {row.activity_id}", "finish_before": day,
            "finish_after": day, "finish_delta": 0, "absorbed": 0, "milestones": [], "critical_added": [],
            "critical_removed": [], "affected": [], "new_clashes": [], "cost": None if row.daily_cost is None else 0}


def save_impacts(
    session: Session, rows: Sequence[DelayEventRow], analysis: core_delay.DelayAnalysis, version: int
) -> None:
    """사건마다 분석의 몫을 적고 analyzed_version 을 단다. 분석에 없는 사건(없는 액티비티)은 넣지 않음으로 적는데,
    준공은 넣는 차례에서 바로 앞 상태의 것이다. flush 만."""
    by_id = {i.event_id: i for i in analysis.impacts}
    last = analysis.base_finish
    for row in sorted(rows, key=lambda r: (r.start_date, str(r.id))):  # core.delay.ordered 와 같은 차례
        found = by_id.get(str(row.id))
        if found is not None:
            row.impact_json, last = impact_json(found), found.finish_after
        else:
            row.impact_json = _missing(row, last)
        row.analyzed_version = version
    session.flush()


def refresh(session: Session, schedule_id: int, *, force: bool = False) -> None:
    """열린 사건 가운데 지금 버전으로 분석하지 않은 것이 있으면(force 면 늘) 열린 사건을 모두 다시 분석해 적는다.

    없는 일정이면 NotFound, 지금 일정이 깨졌으면 ScheduleError. flush 만.
    """
    schedule, conditions, n = load(session, schedule_id)
    rows = open_events(session, schedule_id)
    if not force and all(r.analyzed_version == n for r in rows):
        return
    ready = prepare_stored(schedule, conditions)
    known = {a.id for a in ready.activities}
    analysis = core_delay.analyze(ready, [to_core(r) for r in rows if r.activity_id in known])
    save_impacts(session, rows, analysis, n)


# ── 묶음 자료(DelaysOut) ──────────────────────────────────────────────


def _deadline(conditions: list[dict]) -> date | None:
    """켜진(형식 맞는) finish_by 가운데 가장 이른 기한. 없으면 None."""
    dues = [date.fromisoformat(c.params["date"]) for c in assemble_all(read_conditions(conditions)[0])
            if condition_problem(c) is None and c.enabled and c.kind == "finish_by"]
    return min(dues) if dues else None


def _with_open(open_rows: Sequence[DelayEventRow], current: date) -> date:
    """열린 사건을 넣은 준공 = 넣는 차례로 마지막 사건의 finish_after(열린 사건이 없으면 지금 준공)."""
    if not open_rows:
        return current
    last = max(open_rows, key=lambda r: (r.start_date, str(r.id)))
    return date.fromisoformat(last.impact_json["finish_after"])


def _totals(rows: Sequence[DelayEventRow]) -> dict:
    """모든 사건(열림·반영)의 합. 준공 영향은 준공을 민 근무일만 센다(당겨진 것은 0)."""
    by = dict.fromkeys(RESPONSIBILITIES, 0)
    absorbed = absorbed_events = 0
    costs = []
    for r in rows:
        i = r.impact_json
        if not i:
            continue
        by[r.responsibility] = by.get(r.responsibility, 0) + max(0, i["finish_delta"])
        absorbed += i["absorbed"]
        absorbed_events += i["absorbed"] > 0
        if i["cost"] is not None:
            costs.append(i["cost"])
    return {"finish_impact": sum(by.values()), "by_responsibility": by, "absorbed": absorbed,
            "absorbed_events": absorbed_events, "cost": sum(costs) if costs else None,
            "open_count": sum(r.status == "open" for r in rows)}


def _impact_out(i: dict, names: dict[str, str], resources: dict[str, str]) -> dict | None:
    if not i:
        return None
    return {
        **i,
        "milestones": [{**m, "name": names.get(m["activity_id"], m["activity_id"])} for m in i["milestones"]],
        "new_clashes": [{**c, "name": resources.get(c["resource_id"], c["resource_id"])} for c in i["new_clashes"]],
    }


def _event_out(row: DelayEventRow, n: int, names: dict[str, str], resources: dict[str, str]) -> dict:
    return {
        "id": row.id, "activity_id": row.activity_id, "activity_name": names.get(row.activity_id, row.activity_id),
        "start_date": row.start_date, "days": row.days, "cause": row.cause, "responsibility": row.responsibility,
        "daily_cost": row.daily_cost, "evidence": row.evidence, "source": row.source, "status": row.status,
        "impact": _impact_out(row.impact_json, names, resources), "analyzed_version": row.analyzed_version,
        "reflected_version": row.reflected_version, "stale": row.status == "open" and row.analyzed_version != n,
        "created_by": row.created_by, "created_at": row.created_at,
    }


def report(session: Session, schedule_id: int) -> dict:
    """지연 기록 묶음(DelaysOut 의 칸 그대로). 낡은 분석은 먼저 다시 한다(refresh).

    finish: plan = Plan(실적·기록한 지연 없이, store.view.plan_of), current = 지금 버전, with_open = 열린 사건을 넣은 준공,
    deadline = 가장 이른 finish_by, deadline_float = with_open → deadline 근무일(조건 넣은 달력). 날짜는 date 객체·ISO 글.
    없는 일정이면 NotFound, 지금 일정이 깨졌으면 ScheduleError.
    """
    refresh(session, schedule_id)
    schedule, conditions, n = load(session, schedule_id)
    ready = prepare_stored(schedule, conditions)
    current = run(ready)
    plan = plan_of(session, schedule_id, n, current)
    rows = listed(session, schedule_id)
    with_open = _with_open([r for r in rows if r.status == "open"], current.finish)
    deadline = _deadline(conditions)
    names = {a.id: a.name for a in schedule.activities}
    resources = {r.id: r.name for r in schedule.resources}
    return {
        "schedule_id": schedule_id, "version": n,
        "events": [_event_out(r, n, names, resources) for r in rows],
        "totals": _totals(rows),
        "finish": {
            "plan": plan.finish if plan else None, "current": current.finish, "with_open": with_open,
            "deadline": deadline,
            "deadline_float": WorkCalendar(ready.calendar).workdays_between(with_open, deadline) if deadline else None,
        },
    }
