"""만약에 복사본(scenarios): 만들기(요약을 코드가 채움)·읽기·목록·상태 바꾸기.

복사본은 저장된 일정과 따로 있는 일정 하나다. 반영할 때만 승인(approvals, link_kind 'scenario')으로 들어간다.
status: open → submitted(승인 대기) → applied, 거부·충돌이면 다시 open. 사람이 버리면 discarded.
"""

from collections.abc import Sequence
from datetime import date
from math import inf

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.accel import MIXED_REASON, accel_effect, accel_view, derive_moves
from app.core.calendar import WorkCalendar
from app.core.cpm import CpmResult, compute
from app.core.model import Schedule
from app.core.resources import LevelResult, level
from app.core.shorten import Move
from app.harness.assemble import assemble_all, prepare_stored
from app.harness.checks import check
from app.harness.conditions import condition_problem, read_conditions
from app.store.diff import pred_json
from app.store.drafts import violation_json
from app.store.schedules import (
    NotFound,
    activity_json,
    from_json,
    get_version,
    load,
    run,
    to_json,
)
from app.store.settings import accel_warn_ratio, points_config
from app.store.tables import Scenario
from app.store.view import plan_of

__all__ = ["NotFound", "copy_accel", "create", "get", "listed", "set_status", "summarize"]


def _peak(schedule: Schedule, lv: LevelResult) -> dict | None:
    """맞춘 일정의 자원별 최대 사용 가운데 필요량/용량이 가장 큰 것(같으면 자원 id 순). 쓰는 자원이 없으면 None."""
    if not lv.peaks:
        return None
    best = min(lv.peaks.values(), key=lambda p: (-(p.need / p.capacity if p.capacity > 0 else inf), p.resource_id))
    names = {r.id: r.name for r in schedule.resources}
    return {"resource_id": best.resource_id, "name": names.get(best.resource_id, best.resource_id), "need": best.need,
            "capacity": best.capacity, "when": best.when.isoformat()}


def _changed_count(old: Schedule, old_cpm: CpmResult, new: Schedule, new_cpm: CpmResult) -> int:
    """날짜(ES·EF)·입력 칸·선행 관계 가운데 하나라도 다르거나 한쪽에만 있는 액티비티 수(승인 판단의 diff 와 같은 뜻)."""
    def rows(s: Schedule, cpm: CpmResult) -> dict[str, tuple]:
        preds: dict[str, list[dict]] = {}
        for r in s.relations:
            preds.setdefault(r.succ, []).append(pred_json(r))
        return {a.id: (activity_json(a), preds.get(a.id, []), cpm.rows[a.id].es, cpm.rows[a.id].ef)
                for a in s.activities}

    before, after = rows(old, old_cpm), rows(new, new_cpm)
    return sum(before.get(i) != after.get(i) for i in before.keys() | after.keys())


def summarize(session: Session, schedule_id: int, schedule: Schedule, conditions: list[dict]) -> dict:
    """복사본 요약(JSON 그대로 저장). 날짜 차이는 모두 복사본의 조건 넣은 달력의 근무일이다.

    finish_delta = 지금 버전 준공 → 복사본 준공, plan_delta = Plan 준공 → 복사본 준공(Plan 이 계산되지 않으면 None),
    deadline_float = 복사본 준공 → 가장 이른 켜진 finish_by 기한(없으면 None). violations·uncheckable 은 하네스 점검.
    gain·base_finish·note·recommended 는 단축안이 extra_summary 로 채운다. 깨진 일정이면 ScheduleError.
    """
    current, current_conditions, n = load(session, schedule_id)
    current_cpm = run(current, current_conditions)
    plan = plan_of(session, schedule_id, n, current_cpm)
    ready = prepare_stored(schedule, conditions)
    lv = level(ready, compute(ready), shift=True)
    cal = WorkCalendar(ready.calendar)
    assembled = assemble_all(read_conditions(conditions)[0])
    report = check(schedule, assembled)
    dues = [date.fromisoformat(c.params["date"]) for c in assembled
            if condition_problem(c) is None and c.enabled and c.kind == "finish_by"]
    return {
        "finish": lv.finish.isoformat(),
        "finish_delta": cal.workdays_between(current_cpm.finish, lv.finish),
        "plan_delta": cal.workdays_between(plan.finish, lv.finish) if plan else None,
        "deadline_float": cal.workdays_between(lv.finish, min(dues)) if dues else None,
        "critical_count": sum(row.critical for row in lv.cpm.rows.values()),
        "violations": [violation_json(v) for v in report.violations],
        "uncheckable": len(report.uncheckable),
        "peak": _peak(schedule, lv),
        "changed_count": _changed_count(current, current_cpm, schedule, lv.cpm),
        "gain": None,
        "base_finish": None,
        "note": "",
        "recommended": False,
    }


def copy_accel(
    session: Session, schedule_id: int, base_version: int, schedule: Schedule, conditions: list[dict]
) -> tuple[dict | None, str | None]:
    """만약에 복사본의 당김 효과: (core.accel.accel_view 칸 또는 None, 셀 수 없을 때의 까닭 또는 None).

    바탕 = 그 복사본을 뜬 버전(저장 조건 넣음), 이동 = core.accel.derive_moves. 당김이 없으면(이동 없음)
    (None, None), 당김과 다른 바뀜이 함께 있으면 (None, MIXED_REASON).
    """
    row = get_version(session, schedule_id, base_version)
    base = prepare_stored(from_json(row.snapshot_json), list(row.conditions_json))
    moves = derive_moves(base, prepare_stored(schedule, conditions))
    if moves is None:
        return None, MIXED_REASON
    if not moves:
        return None, None
    cfg = points_config(session)
    result = accel_effect(base, moves, warn_ratio=accel_warn_ratio(session), tf_days=cfg.tf_days,
                          window_weeks=cfg.window_weeks)
    return accel_view(base, result), None


def create(
    session: Session,
    *,
    schedule_id: int,
    base_version: int,
    name: str,
    source: str,
    schedule: Schedule,
    conditions: list[dict],
    moves: Sequence[Move] = (),
    delay_event_ids: Sequence[int] = (),
    created_by: str,
    extra_summary: dict | None = None,
) -> Scenario:
    """복사본 한 줄을 넣고 flush 한다. summary_json 은 summarize + extra_summary. source: 'agent'|'shorten'|'delay'."""
    summary = summarize(session, schedule_id, schedule, conditions) | (extra_summary or {})
    row = Scenario(
        schedule_id=schedule_id, base_version=base_version, name=name, source=source, snapshot_json=to_json(schedule),
        conditions_json=list(conditions), moves_json=[{"id": m.id, "kind": m.kind, "text": m.text} for m in moves],
        delay_event_ids=list(delay_event_ids), summary_json=summary, status="open", created_by=created_by,
    )
    session.add(row)
    session.flush()
    return row


def get(session: Session, sid: int) -> Scenario:
    """없으면 NotFound."""
    row = session.get(Scenario, sid)
    if row is None:
        raise NotFound(sid)
    return row


def listed(session: Session, schedule_id: int, statuses: Sequence[str]) -> list[Scenario]:
    """그 일정의 복사본 가운데 status 가 statuses 인 것, 새것부터."""
    query = (
        select(Scenario)
        .where(Scenario.schedule_id == schedule_id, Scenario.status.in_(list(statuses)))
        .order_by(Scenario.id.desc())
    )
    return list(session.scalars(query))


def set_status(session: Session, row: Scenario, status: str, *, approval_id: int | None = None) -> None:
    """상태를 바꾼다. approval_id 를 주면 그 승인 건을 단다(주지 않으면 마지막 승인 건을 그대로 둔다). flush 만."""
    row.status = status
    if approval_id is not None:
        row.approval_id = approval_id
    session.flush()
