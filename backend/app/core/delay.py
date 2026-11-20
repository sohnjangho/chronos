"""지연 영향 계산: 지연 사건을 차례로 넣어 가며 사건마다 그 몫의 영향을 잰다.

받는 일정은 조건을 넣은 일정이다(부르는 쪽이 `prepare_stored`). core 는 조건을 모른다.

넣기(`insert_delay`)
- 시작 전 task: 기간(od)은 그대로, 시작을 미룬다. 넣기 전 **맞춘** 일정
  (`level(s, compute(s), shift=True)`)의 ES — 사용자가 보는 시작 — 를 그 액티비티 달력
  (꼬리표 포함)의 근무일로 `days` 만큼 민 날을 시작 하한으로 건다.
  - constraint 가 없거나 SNET → `SNET(max(기존, 하한))`.
  - FNLT → 그 제약은 두고, 앞에 숨은 0일 시작 마일스톤 `~<ID>`(SNET=하한, `~<ID>` → `<ID>` FS)
    를 넣는다. 이미 있으면 그 SNET 을 올린다. 결과의 id 목록에서는 `~` 로 시작하는 id 를 뺀다.
- 진행 중(actual_start 있음, actual_finish 없음): `rd = (rd 또는 od) + days`.
- 끝남·마일스톤: 넣지 않고 그 까닭(`FINISHED_NOTE`·`MILESTONE_NOTE`)을 돌려준다.
- `~` 로 시작하는 사용자 id 는 받지 않는다(`DelayInputError`): 사건이 겨누는 id 와,
  `analyze` 가 받은 일정의 액티비티 id.
- `start` 는 차례와 표시에만 쓴다.

재기(`diff_impact`)
- 날짜·준공·주공정은 `level(s, compute(s), shift=True).cpm`, 새 겹침은 맞추기 전
  `level(s, compute(s), shift=False).overloads` 에서 뒤에만 있는 (자원, 날짜).
- 근무일 차이는 꼬리표 없는 일정 달력으로 센다.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date

from app.core.calendar import WorkCalendar
from app.core.cpm import compute
from app.core.model import Activity, Constraint, Relation, Schedule
from app.core.resources import LevelResult, Peak, level

_Dates = dict[str, tuple[date, date]]

FINISHED_NOTE = "이미 끝난 액티비티입니다. 지연이 실적에 들어 있습니다."
MILESTONE_NOTE = "마일스톤에는 기간을 더할 수 없습니다. 앞 작업에 기록해 주세요."
HIDDEN = "~"  # 숨은 도우미 마일스톤 id 의 머리
_HIDDEN_ID = "'~' 로 시작하는 액티비티 id 는 쓸 수 없습니다."


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


class DelayInputError(ValueError):
    def __init__(self, event_id: str, message: str) -> None:
        super().__init__(message)
        self.event_id = event_id
        self.message = message


def ordered(events: Iterable[DelayEvent]) -> list[DelayEvent]:
    """넣는 차례: (start, id) 순."""
    return sorted(events, key=lambda e: (e.start, e.id))


def _target(schedule: Schedule, event: DelayEvent) -> Activity:
    if event.activity_id.startswith(HIDDEN):
        raise DelayInputError(event.id, _HIDDEN_ID)
    a = next((x for x in schedule.activities if x.id == event.activity_id), None)
    if a is None:
        raise DelayInputError(event.id, f"없는 액티비티입니다: {event.activity_id}")
    if event.days < 1:
        raise DelayInputError(event.id, "지연 일수는 1일 이상이어야 합니다.")
    return a


def _with(schedule: Schedule, new: Activity) -> Schedule:
    acts = tuple(new if a.id == new.id else a for a in schedule.activities)
    return replace(schedule, activities=acts)


def _raised(c: Constraint | None, bound: date) -> Constraint:
    """SNET(max(기존, 하한)). 기존이 없으면 하한."""
    return Constraint("SNET", bound if c is None else max(c.date, bound))


def _hold(schedule: Schedule, a: Activity, bound: date) -> Schedule:
    """FNLT 는 그대로 두고 앞의 숨은 시작 마일스톤으로 시작을 미룬다."""
    hid = HIDDEN + a.id
    old = next((x for x in schedule.activities if x.id == hid), None)
    if old is not None:
        return _with(schedule, replace(old, constraint=_raised(old.constraint, bound)))
    gate = Activity(hid, hid, "start_ms", a.wbs, 0, constraint=Constraint("SNET", bound))
    return replace(
        schedule,
        activities=schedule.activities + (gate,),
        relations=schedule.relations + (Relation(hid, a.id),),
    )


def _leveled_dates(schedule: Schedule) -> _Dates:
    return level(schedule, compute(schedule), shift=True).dates


def _push_start(schedule: Schedule, a: Activity, days: int, dates: _Dates) -> Schedule:
    es = dates[a.id][0]  # 맞춘 일정의 시작
    bound = WorkCalendar(schedule.calendar).shift(es, days, a.tags)
    if a.constraint is not None and a.constraint.type == "FNLT":
        return _hold(schedule, a, bound)
    return _with(schedule, replace(a, constraint=_raised(a.constraint, bound)))


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
    return _push_start(schedule, a, event.days, dates or _leveled_dates(schedule)), None


@dataclass(frozen=True)
class _State:
    """일정 하나를 잰 값."""

    schedule: Schedule
    level: LevelResult
    overloads: tuple[Peak, ...]  # 맞추기 전 겹침


def _measure(schedule: Schedule) -> _State:
    cpm = compute(schedule)
    return _State(schedule, level(schedule, cpm, shift=True), level(schedule, cpm, shift=False).overloads)


def _shown(state: _State) -> list[Activity]:
    """일정 차례의 액티비티. 숨은 도우미는 뺀다."""
    return [a for a in state.schedule.activities if not a.id.startswith(HIDDEN)]


def _affected(before: _State, after: _State) -> tuple[str, ...]:
    b, a = before.level.dates, after.level.dates
    return tuple(x.id for x in _shown(after) if x.id in b and b[x.id] != a[x.id])


def _milestones(cal: WorkCalendar, before: _State, after: _State) -> tuple[MilestoneShift, ...]:
    b, a = before.level.dates, after.level.dates
    out = []
    for x in _shown(after):
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
        critical_added=tuple(x.id for x in _shown(after) if x.id in crit_a and x.id not in crit_b),
        critical_removed=tuple(x.id for x in _shown(before) if x.id in crit_b and x.id not in crit_a),
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
    if events and any(a.id.startswith(HIDDEN) for a in schedule.activities):
        raise DelayInputError(events[0].id, _HIDDEN_ID)  # 숨은 도우미와 헷갈리지 않게
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
    )
