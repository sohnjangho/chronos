"""주요 자원 겹침과 맞춤.

쓰는 법(`usage`)
- 액티비티 하나는 `resources` 에 적힌 자원을 시작일부터 종료일까지, 자기 달력
  (꼬리표 포함)의 근무일마다 1 단위씩 쓴다.
- 마일스톤(od=0)은 쓰지 않는다. 일정에 없는 자원 id 는 세지 않는다.

맞춤(`level(..., shift=True)`)
- 선행이 모두 놓인 액티비티 가운데 우선순위가 가장 높은 것부터 하나씩 놓는다.
  우선순위는 받은 `cpm` 의 (ES 이른 것, TF 작은 것, id 순)이며, 밀린 뒤에 다시
  매기지 않는다. `cpm` 은 같은 일정의 `compute(schedule)` 이어야 한다.
- 자리가 없으면 그 액티비티의 `pinned_start` 를 뒤로 잡고, 후행 날짜는 `compute`
  로 다시 구한다. 관계·달력 규칙은 전부 `cpm.compute` 것을 쓴다.
  (맞추는 동안에는 옮긴 액티비티의 후행만 담은 작은 일정을 계산한다. 그 밖의
  선행은 지금 날짜를 실적으로 넣어 고정한다. 마지막 결과는 전체 일정을 계산한 것이다.)
  이 방식은 `compute` 의 규칙 하나에 기댄다: actual_start 와 actual_finish 가 둘 다
  있는 액티비티는 정확히 그 날짜에 놓인다.
- 실적(actual_start 또는 actual_finish)이 있는 액티비티는 옮기지 않는다.
  용량 0 이하인 자원을 쓰는 액티비티도 스스로는 옮기지 않는다(선행에 밀릴 수는 있다).
- FNLT 는 맞춤을 막지 않는다. 넘으면 `LevelResult.cpm` 의 tf 가 음수가 된다.
- `LevelResult.cpm` 의 여유(tf·ff)와 주공정은 관계와 `pinned_start` 만 반영한다.
  자원이 비어 있는지는 반영하지 않는다(여유만큼 늦추면 자원이 겹칠 수 있다).

`LevelResult.schedule` 은 저장하지 않는다
- 계산과 화면 표시에만 쓰는 임시 값이다. 절대 저장하지 않는다. 저장하는 것은 사용자가
  만든 일정이고, 읽을 때 `level` 을 다시 돌린다.
- 이 일정에는 맞춤이 옮긴 액티비티의 `pinned_start` 가 들어 있다. 그리고 actual_finish
  만 있는 액티비티 가운데 맞춤 때문에 날짜가 달라질 것에는 계산된 `actual_start`
  (맞추기 전 CPM 시작일)가 들어 있다. 이 값은 실제 실적이 아니다.
"""

import heapq
from dataclasses import dataclass, replace
from datetime import date, timedelta

from app.core.calendar import WorkCalendar
from app.core.cpm import CpmResult, compute
from app.core.model import Activity, Schedule

_DAY = timedelta(days=1)
# 자리를 찾아 훑는 한도: 사업 종료일(CPM) 뒤 달력일 수(약 5년). 넘으면 옮기지 않는다.
MAX_SHIFT_DAYS = 1826

_Dates = dict[str, tuple[date, date]]
_Load = dict[tuple[str, date], int]  # (자원 id, 날짜) → 이미 놓인 필요량


@dataclass(frozen=True)
class Peak:
    resource_id: str
    when: date
    need: int
    capacity: int


@dataclass(frozen=True)
class LevelResult:
    """맞춤(또는 점검) 결과.

    dates: id → (ES, EF). 항상 cpm.rows 의 (es, ef) 와 같다.
    finish: 사업 종료일. 항상 cpm.finish 와 같다.
    peaks: 쓰이는 자원마다 필요량이 가장 큰 날(동률이면 이른 날). schedule.resources 순.
    overloads: 필요량이 용량을 넘는 (날짜, 자원) 마다 하나. 날짜 순, 같은 날은 자원 id 순.
    shifted: 받은 cpm 과 날짜가 달라진 id. 처음 달라진 순서(직접 옮긴 것, 이어서 따라 밀린 후행).
    schedule: 임시 값, 저장 금지. 받은 일정에 pinned_start(와 계산된 actual_start)를 넣은 것.
        shift=False 면 받은 일정 그대로다. 모듈 설명글 참고.
    cpm: compute(schedule) 결과. shift=False 면 받은 cpm 그대로다.
    """

    dates: dict[str, tuple[date, date]]
    finish: date
    peaks: dict[str, Peak]
    overloads: tuple[Peak, ...]
    shifted: tuple[str, ...]
    schedule: Schedule
    cpm: CpmResult


def _needs(a: Activity, known: dict[str, int]) -> tuple[str, ...]:
    """a 가 쓰는 자원 id(일정에 있는 것만, 중복 없이). 마일스톤은 쓰지 않는다."""
    if a.od == 0:
        return ()
    return tuple(r for r in dict.fromkeys(a.resources) if r in known)


def _workdays(cal: WorkCalendar, a: Activity, span: tuple[date, date]) -> list[date]:
    days = []
    d = span[0]
    while d <= span[1]:
        if cal.is_workday(d, a.tags):
            days.append(d)
        d += _DAY
    return days


def usage(
    schedule: Schedule, dates: dict[str, tuple[date, date]]
) -> dict[str, dict[date, tuple[str, ...]]]:
    """자원 id → 날짜 → 그 날 그 자원을 쓰는 액티비티 id 들(정렬).

    쓰이는 자원만 `schedule.resources` 순서로, 날짜는 이른 순으로 담는다.
    아무도 쓰지 않는 날(쉬는 날 포함)은 들어가지 않는다.
    """
    cal = WorkCalendar(schedule.calendar)
    known = {r.id: r.capacity for r in schedule.resources}
    raw: dict[str, dict[date, list[str]]] = {}
    for a in schedule.activities:
        rids = _needs(a, known)
        if not rids:
            continue
        days = _workdays(cal, a, dates[a.id])
        for rid in rids:
            for d in days:
                raw.setdefault(rid, {}).setdefault(d, []).append(a.id)
    return {
        rid: {d: tuple(sorted(raw[rid][d])) for d in sorted(raw[rid])}
        for rid in known
        if rid in raw
    }


def _peaks(used: dict[str, dict[date, tuple[str, ...]]], capacity: dict[str, int]) -> dict[str, Peak]:
    """자원마다 필요량이 가장 큰 날(동률이면 이른 날)."""
    peaks = {}
    for rid, days in used.items():
        when = min(days, key=lambda d: (-len(days[d]), d))
        peaks[rid] = Peak(rid, when, len(days[when]), capacity[rid])
    return peaks


def _overloads(
    used: dict[str, dict[date, tuple[str, ...]]], capacity: dict[str, int]
) -> tuple[Peak, ...]:
    """용량을 넘는 (날짜, 자원) 마다 하나씩. 날짜 순, 같은 날은 자원 id 순."""
    over = [
        Peak(rid, d, len(ids), capacity[rid])
        for rid, days in used.items()
        for d, ids in days.items()
        if len(ids) > capacity[rid]
    ]
    return tuple(sorted(over, key=lambda p: (p.when, p.resource_id)))


def _order(schedule: Schedule, cpm: CpmResult) -> list[str]:
    """놓는 순서: 선행이 모두 놓인 것 가운데 (ES, TF, id) 가 가장 작은 것부터."""
    indegree = {a.id: 0 for a in schedule.activities}
    succs: dict[str, list[str]] = {i: [] for i in indegree}
    for r in schedule.relations:
        indegree[r.succ] += 1
        succs[r.pred].append(r.succ)

    def key(i: str) -> tuple[date, int, str]:
        return cpm.rows[i].es, cpm.rows[i].tf, i

    ready = [key(i) for i in indegree if indegree[i] == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        i = heapq.heappop(ready)[2]
        order.append(i)
        for s in succs[i]:
            indegree[s] -= 1
            if indegree[s] == 0:
                heapq.heappush(ready, key(s))
    return order


def _book(load: _Load, rids: tuple[str, ...], days: list[date]) -> None:
    for rid in rids:
        for d in days:
            load[rid, d] = load.get((rid, d), 0) + 1


def _slot(
    cal: WorkCalendar,
    a: Activity,
    rids: tuple[str, ...],
    start: date,
    limit: date,
    load: _Load,
    capacity: dict[str, int],
) -> date | None:
    """start 이후 a 가 용량 안에 들어가는 가장 이른 시작일. limit 까지 없으면 None."""
    while start <= limit:
        days = _workdays(cal, a, (start, cal.add_workdays(start, a.od, a.tags)))
        full = [d for d in days if any(load.get((r, d), 0) >= capacity[r] for r in rids)]
        if not full:
            return start
        start = cal.next_workday(full[-1] + _DAY, a.tags)  # 막힌 마지막 날 뒤로 건너뛴다
    return None


def _is_actual(a: Activity) -> bool:
    return a.actual_start is not None or a.actual_finish is not None


def _apply(schedule: Schedule, pins: dict[str, date], held: dict[str, date]) -> Schedule:
    """pins 는 pinned_start 로, held 는 actual_start 로 넣은 일정."""
    if not pins and not held:
        return schedule
    acts = []
    for a in schedule.activities:
        if a.id in pins:
            a = replace(a, pinned_start=pins[a.id])
        elif a.id in held:
            a = replace(a, actual_start=held[a.id])
        acts.append(a)
    return replace(schedule, activities=tuple(acts))


def _early(cpm: CpmResult) -> _Dates:
    return {i: (row.es, row.ef) for i, row in cpm.rows.items()}


def _successors(schedule: Schedule) -> dict[str, list[str]]:
    succs: dict[str, list[str]] = {a.id: [] for a in schedule.activities}
    for r in schedule.relations:
        succs[r.pred].append(r.succ)
    return succs


def _below(succs: dict[str, list[str]], i: str) -> set[str]:
    """i 의 후행 전부(후행의 후행까지)."""
    seen: set[str] = set()
    todo = [i]
    while todo:
        for s in succs[todo.pop()]:
            if s not in seen:
                seen.add(s)
                todo.append(s)
    return seen


def _pushed(schedule: Schedule, below: set[str], dates: _Dates, held: dict[str, date]) -> _Dates:
    """below(방금 옮긴 액티비티의 후행들)의 새 날짜.

    below 와 그 직접 선행만 담은 일정을 계산한다. below 밖의 선행은 dates 의 날짜로 고정한다.
    """
    rels = tuple(r for r in schedule.relations if r.succ in below)
    fixed = {r.pred for r in rels} - below
    part = []
    for a in schedule.activities:
        if a.id in below:
            part.append(replace(a, actual_start=held[a.id]) if a.id in held else a)
        elif a.id in fixed:
            start, finish = dates[a.id]
            part.append(replace(a, actual_start=start, actual_finish=finish))
    rows = compute(replace(schedule, activities=tuple(part), relations=rels)).rows
    return {j: (rows[j].es, rows[j].ef) for j in below}


def _place(
    schedule: Schedule, cpm: CpmResult, capacity: dict[str, int]
) -> tuple[dict[str, date], tuple[str, ...]]:
    """하나씩 놓으며 옮길 시작일(pins)과 날짜가 달라진 id(처음 달라진 순서)를 구한다."""
    cal = WorkCalendar(schedule.calendar)
    acts = {a.id: a for a in schedule.activities}
    base = _early(cpm)
    dates = dict(base)
    succs = _successors(schedule)
    # 종료 실적만 있는 액티비티는 시작일이 선행을 따라 계산된다. 계산된 시작일에 붙잡아 둔다.
    held = {a.id: base[a.id][0] for a in acts.values() if a.actual_finish and not a.actual_start}
    limit = cpm.finish + MAX_SHIFT_DAYS * _DAY
    load: _Load = {}
    for a in acts.values():  # 실적이 있는 것은 못 옮기므로 먼저 자리를 차지한다
        if _is_actual(a):
            _book(load, _needs(a, capacity), _workdays(cal, a, base[a.id]))
    pins: dict[str, date] = {}
    shifted: dict[str, None] = {}
    for i in _order(schedule, cpm):
        a = acts[i]
        rids = _needs(a, capacity)
        if not rids or _is_actual(a):
            continue
        start = dates[i][0]
        if all(capacity[r] > 0 for r in rids):
            slot = _slot(cal, a, rids, start, limit, load, capacity)
            if slot is not None and slot != start:
                pins[i] = slot
                dates[i] = (slot, cal.add_workdays(slot, a.od, a.tags))
                below = _below(succs, i)
                if below:
                    dates.update(_pushed(schedule, below, dates, held))
                moved = [j for j in base if j in below and dates[j] != base[j]]
                shifted.update(dict.fromkeys([i] + moved))
        _book(load, rids, _workdays(cal, a, dates[i]))
    return pins, tuple(shifted)


def _pinned(schedule: Schedule, cpm: CpmResult, pins: dict[str, date]) -> tuple[Schedule, CpmResult]:
    """pins 를 넣은 일정과 그 계산 결과. 실적이 있는 액티비티의 날짜는 처음 그대로다."""
    out = _apply(schedule, pins, {})
    result = compute(out)
    held = {
        a.id: cpm.rows[a.id].es
        for a in schedule.activities
        if a.actual_finish and not a.actual_start and result.rows[a.id].es != cpm.rows[a.id].es
    }
    if held:
        out = _apply(schedule, pins, held)
        result = compute(out)
    return out, result


def level(schedule: Schedule, cpm: CpmResult, *, shift: bool = True) -> LevelResult:
    capacity = {r.id: r.capacity for r in schedule.resources}
    shifted: tuple[str, ...] = ()
    if shift:
        pins, shifted = _place(schedule, cpm, capacity)
        schedule, cpm = _pinned(schedule, cpm, pins)
    dates = _early(cpm)
    used = usage(schedule, dates)
    return LevelResult(
        dates, cpm.finish, _peaks(used, capacity), _overloads(used, capacity), shifted, schedule, cpm
    )
