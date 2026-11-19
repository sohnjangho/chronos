"""주요 자원 겹침과 맞춤.

액티비티 하나는 `resources` 에 적힌 자원을 시작일부터 종료일까지, 자기 달력의
근무일마다 1 단위씩 쓴다. 마일스톤(od=0)과 일정에 없는 자원 id 는 세지 않는다.

맞춤(`shift=True`)은 선행이 모두 놓인 액티비티 가운데 우선순위(이른 ES, 작은 TF,
id 순)가 가장 높은 것부터 하나씩 놓는다. 자리가 없으면 그 액티비티만 뒤로 옮기고,
후행 날짜는 `compute` 로 다시 구한다(옮긴 날짜를 SNET 조건으로 넣어 계산).
"""

import heapq
from dataclasses import dataclass, replace
from datetime import date, timedelta

from app.core.calendar import WorkCalendar
from app.core.cpm import CpmResult, compute
from app.core.model import Activity, Constraint, Schedule

_DAY = timedelta(days=1)
# 자리를 찾아 훑는 한도: 사업 종료일(CPM) 뒤 달력일 수(약 5년). 넘으면 옮기지 않는다.
MAX_SHIFT_DAYS = 1826

_Dates = dict[str, tuple[date, date]]
_Usage = dict[tuple[str, date], int]  # (자원 id, 날짜) → 필요량


@dataclass(frozen=True)
class Peak:
    resource_id: str
    when: date
    need: int
    capacity: int


@dataclass(frozen=True)
class LevelResult:
    dates: dict[str, tuple[date, date]]
    finish: date
    peaks: dict[str, Peak]
    overloads: tuple[Peak, ...]
    shifted: tuple[str, ...]


def _needs(a: Activity, capacity: dict[str, int]) -> tuple[str, ...]:
    """a 가 쓰는 자원 id(일정에 있는 것만, 중복 없이). 마일스톤은 쓰지 않는다."""
    if a.od == 0:
        return ()
    return tuple(r for r in dict.fromkeys(a.resources) if r in capacity)


def _workdays(cal: WorkCalendar, a: Activity, span: tuple[date, date]) -> list[date]:
    days = []
    d = span[0]
    while d <= span[1]:
        if cal.is_workday(d, a.tags):
            days.append(d)
        d += _DAY
    return days


def _book(usage: _Usage, rids: tuple[str, ...], days: list[date]) -> None:
    for rid in rids:
        for d in days:
            usage[rid, d] = usage.get((rid, d), 0) + 1


def _usage(schedule: Schedule, cal: WorkCalendar, capacity: dict[str, int], dates: _Dates) -> _Usage:
    usage: _Usage = {}
    for a in schedule.activities:
        rids = _needs(a, capacity)
        if rids:
            _book(usage, rids, _workdays(cal, a, dates[a.id]))
    return usage


def _peaks(schedule: Schedule, usage: _Usage) -> dict[str, Peak]:
    """자원마다 필요량이 가장 큰 날(동률이면 이른 날). 아무도 안 쓰는 자원은 뺀다."""
    best: dict[str, tuple[int, date]] = {}
    for (rid, d), need in usage.items():
        if rid not in best or (-need, d) < (-best[rid][0], best[rid][1]):
            best[rid] = (need, d)
    return {
        r.id: Peak(r.id, best[r.id][1], best[r.id][0], r.capacity)
        for r in schedule.resources
        if r.id in best
    }


def _overloads(usage: _Usage, capacity: dict[str, int]) -> tuple[Peak, ...]:
    """용량을 넘는 (날짜, 자원) 마다 하나씩. 날짜 순, 같은 날은 자원 id 순."""
    over = [
        Peak(rid, d, need, capacity[rid])
        for (rid, d), need in usage.items()
        if need > capacity[rid]
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


def _slot(
    cal: WorkCalendar,
    a: Activity,
    rids: tuple[str, ...],
    start: date,
    limit: date,
    usage: _Usage,
    capacity: dict[str, int],
) -> date | None:
    """start 이후 a 가 용량 안에 들어가는 가장 이른 시작일. limit 까지 없으면 None."""
    while start <= limit:
        days = _workdays(cal, a, (start, cal.add_workdays(start, a.od, a.tags)))
        full = [d for d in days if any(usage.get((r, d), 0) >= capacity[r] for r in rids)]
        if not full:
            return start
        start = cal.next_workday(full[-1] + _DAY, a.tags)  # 막힌 마지막 날 뒤로 건너뛴다
    return None


def _recompute(schedule: Schedule, pins: dict[str, date]) -> _Dates:
    """옮긴 시작일을 SNET 으로 넣고 경로 계산을 다시 해, 후행까지 관계대로 민다."""
    acts = tuple(
        replace(a, constraint=Constraint("SNET", pins[a.id])) if a.id in pins else a
        for a in schedule.activities
    )
    rows = compute(replace(schedule, activities=acts)).rows
    return {i: (row.es, row.ef) for i, row in rows.items()}


def _is_actual(a: Activity) -> bool:
    return a.actual_start is not None or a.actual_finish is not None


def _shift(
    schedule: Schedule, cpm: CpmResult, cal: WorkCalendar, capacity: dict[str, int]
) -> tuple[_Dates, tuple[str, ...]]:
    acts = {a.id: a for a in schedule.activities}
    base: _Dates = {i: (row.es, row.ef) for i, row in cpm.rows.items()}
    dates = base
    limit = cpm.finish + MAX_SHIFT_DAYS * _DAY
    usage: _Usage = {}
    for a in schedule.activities:  # 실적이 있는 것은 못 옮기므로 먼저 자리를 차지한다
        if _is_actual(a):
            _book(usage, _needs(a, capacity), _workdays(cal, a, dates[a.id]))
    pins: dict[str, date] = {}
    shifted: dict[str, None] = {}
    for i in _order(schedule, cpm):
        a = acts[i]
        rids = _needs(a, capacity)
        if not rids or _is_actual(a):
            continue
        start = dates[i][0]
        if all(capacity[r] > 0 for r in rids):
            slot = _slot(cal, a, rids, start, limit, usage, capacity)
            if slot is not None and slot != start:
                pins[i] = slot
                dates = _recompute(schedule, pins)
                shifted.update(dict.fromkeys([i] + [j for j in dates if dates[j] != base[j]]))
        _book(usage, rids, _workdays(cal, a, dates[i]))
    return dates, tuple(shifted)


def level(schedule: Schedule, cpm: CpmResult, *, shift: bool = True) -> LevelResult:
    cal = WorkCalendar(schedule.calendar)
    capacity = {r.id: r.capacity for r in schedule.resources}
    dates: _Dates = {i: (row.es, row.ef) for i, row in cpm.rows.items()}
    shifted: tuple[str, ...] = ()
    if shift:
        dates, shifted = _shift(schedule, cpm, cal, capacity)
    usage = _usage(schedule, cal, capacity, dates)
    finish = max(ef for _, ef in dates.values())
    return LevelResult(dates, finish, _peaks(schedule, usage), _overloads(usage, capacity), shifted)
