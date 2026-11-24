"""지연 영향 계산: 지연 사건을 차례로 넣어 가며 사건마다 그 몫의 영향을 잰다.

받는 일정은 조건을 넣은 일정이다(부르는 쪽이 `prepare_stored`). core 는 조건을 모른다.

넣기(`insert_delay`)
- 시작 전 task: 기간(od)은 그대로, 시작을 미룬다. 넣기 전 **맞춘** 일정
  (`level(s, compute(s), shift=True)`)의 ES — 사용자가 보는 시작 — 를 그 액티비티 달력
  (꼬리표 포함)의 근무일로 `days` 만큼 민 날을 `start_floor = max(기존 start_floor, 하한)` 로
  건다. 사용자 조건(SNET·FNLT)은 건드리지 않는다.
- 진행 중(actual_start 있음, actual_finish 없음): `rd = (rd 또는 od) + days`.
- 끝남·마일스톤: 넣지 않고 그 까닭(`FINISHED_NOTE`·`MILESTONE_NOTE`)을 돌려준다.
- `start` 는 차례와 표시에만 쓴다.

재기(`diff_impact`)
- 날짜·준공·주공정은 `level(s, compute(s), shift=True).cpm`, 새 겹침은 맞추기 전
  `level(s, compute(s), shift=False).overloads` 에서 뒤에만 있는 (자원, 날짜).
- 근무일 차이는 꼬리표 없는 일정 달력으로 센다.
- 넣은 지연으로 준공이 오히려 당겨지면(맞춤 순서가 바뀐 탓) finish_delta 는 잰 그대로 두고
  `note = EARLIER_NOTE`, absorbed = days 로 한다(부르는 쪽이 준 note 가 있으면 그대로).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date

from app.core.calendar import WorkCalendar
from app.core.cpm import CpmResult, compute
from app.core.model import Activity, Schedule
from app.core.resources import LevelResult, Peak, level

_Dates = dict[str, tuple[date, date]]

FINISHED_NOTE = "이미 끝난 액티비티입니다. 지연이 실적에 들어 있습니다."
MILESTONE_NOTE = "마일스톤에는 기간을 더할 수 없습니다. 앞 작업에 기록해 주세요."
EARLIER_NOTE = "자원 맞춤 순서가 바뀌어 준공이 당겨졌습니다 — 지연 자체의 효과는 아닙니다."


@dataclass(frozen=True)
class DelayEvent:
    id: str
    activity_id: str
    start: date
    days: int
    daily_cost: int | None = None


@dataclass(frozen=True)
class MilestoneShift:
    activity_id: str
    before: date
    after: date
    delta: int  # 근무일


@dataclass(frozen=True)
class Clash:
    """새로 생긴(맞추기 전) 자원 초과. 자원마다 하나."""

    resource_id: str
    first: date
    days: int
    over: int  # 가장 큰 (need − capacity)


@dataclass(frozen=True)
class EventImpact:
    event_id: str
    applied: bool
    note: str | None
    finish_before: date
    finish_after: date
    finish_delta: int
    absorbed: int
    milestones: tuple[MilestoneShift, ...]
    critical_added: tuple[str, ...]
    critical_removed: tuple[str, ...]
    affected: tuple[str, ...]
    new_clashes: tuple[Clash, ...]
    cost: int | None


@dataclass(frozen=True)
class DelayAnalysis:
    base_finish: date
    final_finish: date
    total_delta: int
    total_absorbed: int
    impacts: tuple[EventImpact, ...]
    # 처음·마지막 상태(맞춘 CPM) — 관리 포인트 가정 계산(app.points.service.what_if)이 다시 맞추지 않고 쓴다
    base_cpm: CpmResult | None = None
    final_schedule: Schedule | None = None
    final_cpm: CpmResult | None = None


class DelayInputError(ValueError):
    def __init__(self, event_id: str, message: str) -> None:
        super().__init__(message)
        self.event_id = event_id
        self.message = message


def ordered(events: Iterable[DelayEvent]) -> list[DelayEvent]:
    """넣는 차례: (start, id) 순."""
    return sorted(events, key=lambda e: (e.start, e.id))


def _target(schedule: Schedule, event: DelayEvent) -> Activity:
    a = next((x for x in schedule.activities if x.id == event.activity_id), None)
    if a is None:
        raise DelayInputError(event.id, f"없는 액티비티입니다: {event.activity_id}")
    if event.days < 1:
        raise DelayInputError(event.id, "지연 일수는 1일 이상이어야 합니다.")
    return a


def _with(schedule: Schedule, new: Activity) -> Schedule:
    acts = tuple(new if a.id == new.id else a for a in schedule.activities)
    return replace(schedule, activities=acts)


def _leveled_dates(schedule: Schedule) -> _Dates:
    return level(schedule, compute(schedule), shift=True).dates


def _push_start(schedule: Schedule, a: Activity, days: int, dates: _Dates) -> Schedule:
    es = dates[a.id][0]  # 맞춘 일정의 시작
    floor = WorkCalendar(schedule.calendar).shift(es, days, a.tags)
    if a.start_floor is not None:
        floor = max(a.start_floor, floor)
    return _with(schedule, replace(a, start_floor=floor))


def insert_delay(schedule: Schedule, event: DelayEvent) -> tuple[Schedule, str | None]:
    """(넣은 일정, 넣지 못한 까닭). 넣지 못하면 받은 일정을 그대로 돌려준다."""
    return _insert(schedule, event, None)


def _insert(
    schedule: Schedule, event: DelayEvent, dates: _Dates | None
) -> tuple[Schedule, str | None]:
    """dates 는 이 일정의 맞춘 (ES, EF). None 이면 여기서 구한다."""
    a = _target(schedule, event)
    if a.actual_finish is not None:
        return schedule, FINISHED_NOTE
    if a.kind != "task":
        return schedule, MILESTONE_NOTE
    if a.actual_start is not None:
        rd = (a.rd if a.rd is not None else a.od) + event.days
        return _with(schedule, replace(a, rd=rd)), None
    if dates is None:
        dates = _leveled_dates(schedule)
    return _push_start(schedule, a, event.days, dates), None


@dataclass(frozen=True)
class _State:
    """일정 하나를 잰 값."""

    schedule: Schedule
    level: LevelResult
    overloads: tuple[Peak, ...]  # 맞추기 전 겹침


def _measure(schedule: Schedule) -> _State:
    cpm = compute(schedule)
    return _State(schedule, level(schedule, cpm, shift=True), level(schedule, cpm, shift=False).overloads)


def _affected(before: _State, after: _State) -> tuple[str, ...]:
    b, a = before.level.dates, after.level.dates
    return tuple(x.id for x in after.schedule.activities if x.id in b and b[x.id] != a[x.id])


def _milestones(cal: WorkCalendar, before: _State, after: _State) -> tuple[MilestoneShift, ...]:
    b, a = before.level.dates, after.level.dates
    out = []
    for x in after.schedule.activities:
        if x.kind != "task" and x.id in b and b[x.id][1] != a[x.id][1]:
            old, new = b[x.id][1], a[x.id][1]
            out.append(MilestoneShift(x.id, old, new, cal.workdays_between(old, new)))
    return tuple(out)


def _critical(state: _State) -> set[str]:
    return {i for i, row in state.level.cpm.rows.items() if row.critical}


def _new_clashes(before: _State, after: _State) -> tuple[Clash, ...]:
    """뒤에만 있는 (자원, 날짜) 초과를 자원마다 묶는다: 첫 날·날 수·가장 큰 초과. 첫 날 차례."""
    old = {(p.resource_id, p.when) for p in before.overloads}
    grouped: dict[str, list[Peak]] = {}
    for p in after.overloads:  # 날짜 순, 같은 날은 자원 id 순
        if (p.resource_id, p.when) not in old:
            grouped.setdefault(p.resource_id, []).append(p)
    return tuple(
        Clash(rid, ps[0].when, len(ps), max(p.need - p.capacity for p in ps))
        for rid, ps in grouped.items()
    )


def _cost(daily_cost: int | None, applied: bool, finish_delta: int) -> int | None:
    if daily_cost is None:
        return None
    return daily_cost * finish_delta if applied and finish_delta > 0 else 0


def _impact(
    before: _State,
    after: _State,
    *,
    event_id: str,
    days: int,
    daily_cost: int | None,
    applied: bool,
    note: str | None,
) -> EventImpact:
    cal = WorkCalendar(before.schedule.calendar)
    start, end = before.level.finish, after.level.finish
    delta = cal.workdays_between(start, end)
    if applied and delta < 0 and note is None:  # 욕심쟁이 맞춤의 순서가 바뀐 탓(재 본 값은 그대로 둔다)
        note = EARLIER_NOTE
    crit_b, crit_a = _critical(before), _critical(after)
    return EventImpact(
        event_id=event_id,
        applied=applied,
        note=note,
        finish_before=start,
        finish_after=end,
        finish_delta=delta,
        absorbed=max(0, days - max(0, delta)) if applied else 0,
        milestones=_milestones(cal, before, after),
        critical_added=tuple(x.id for x in after.schedule.activities if x.id in crit_a and x.id not in crit_b),
        critical_removed=tuple(x.id for x in before.schedule.activities if x.id in crit_b and x.id not in crit_a),
        affected=_affected(before, after),
        new_clashes=_new_clashes(before, after),
        cost=_cost(daily_cost, applied, delta),
    )


def diff_impact(
    before: Schedule,
    after: Schedule,
    *,
    event_id: str,
    days: int,
    daily_cost: int | None,
    applied: bool = True,
    note: str | None = None,
) -> EventImpact:
    """두 일정 사이의 영향. 실적에서 감지한 지연(이미 일정에 들어감)에도 쓴다."""
    return _impact(
        _measure(before),
        _measure(after),
        event_id=event_id,
        days=days,
        daily_cost=daily_cost,
        applied=applied,
        note=note,
    )


def analyze(schedule: Schedule, events: Sequence[DelayEvent]) -> DelayAnalysis:
    """`ordered` 차례로 하나씩 넣어 가며 각 사건의 몫을 잰다. ScheduleError 는 그대로 나간다."""
    events = ordered(events)
    for e in events:  # 받은 일정 기준으로 계산 전에 다 확인한다
        _target(schedule, e)
    base = state = _measure(schedule)
    impacts = []
    for e in events:
        changed, note = _insert(state.schedule, e, state.level.dates)
        nxt = state if note else _measure(changed)
        impacts.append(
            _impact(
                state,
                nxt,
                event_id=e.id,
                days=e.days,
                daily_cost=e.daily_cost,
                applied=note is None,
                note=note,
            )
        )
        state = nxt
    cal = WorkCalendar(schedule.calendar)
    return DelayAnalysis(
        base_finish=base.level.finish,
        final_finish=state.level.finish,
        total_delta=cal.workdays_between(base.level.finish, state.level.finish),
        total_absorbed=sum(i.absorbed for i in impacts),
        impacts=tuple(impacts),
        base_cpm=base.level.cpm,
        final_schedule=state.schedule,
        final_cpm=state.level.cpm,
    )
