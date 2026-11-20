"""지연 사건(delay_events): 열린 사건 읽기, core 모양으로 바꾸기, 반영 표시, 열린 사건을 넣은 기준 일정.

사건은 'open'(아직 일정에 없음) → 'reflected'(그 버전에 들어감) 두 상태라 두 번 세지 않는다. 열린 사건만 일정에 넣는다.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import delay as core_delay
from app.core.model import Schedule
from app.harness.assemble import prepare_stored
from app.store.schedules import load
from app.store.tables import DelayEvent as DelayEventRow

__all__ = ["DelayEventRow", "DelayedBase", "delayed_base", "mark_reflected", "open_events", "to_core"]


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
