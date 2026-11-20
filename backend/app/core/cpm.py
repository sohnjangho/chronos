"""경로 계산(CPM): 위상 정렬 한 번, 앞으로·거꾸로 한 번씩 훑는다.

날짜 뜻
- task: ES 는 시작하는 날(아침), EF 는 끝나는 날(저녁, 포함).
- start_ms: ES=EF, 그 날 아침의 한 점.
- finish_ms: ES=EF, 그 날 저녁의 한 점.
아침·저녁을 구분하므로 "저녁 → 아침" 으로 이어질 때만 하루가 넘어간다
(FS lag 0: 후행 ES = 선행 EF 의 다음 근무일, 선행이 start_ms 면 같은 날).
"""

import heapq
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.core.calendar import NoWorkdayError, WorkCalendar
from app.core.model import Activity, Relation, Schedule

_DAY = timedelta(days=1)
_AM, _PM = 0, 1  # 하루 안의 위치: 아침 / 저녁

_Dates = dict[str, tuple[date, date]]  # id → (시작 쪽 날짜, 종료 쪽 날짜)


@dataclass(frozen=True)
class CpmRow:
    es: date
    ef: date
    ls: date
    lf: date
    tf: int
    ff: int
    critical: bool


@dataclass(frozen=True)
class CpmResult:
    rows: dict[str, CpmRow]
    finish: date
    critical_path: tuple[str, ...]


ErrorCode = Literal[
    "cycle", "dangling_ref", "bad_duration", "empty", "duplicate_id", "no_workdays"
]


class ScheduleError(Exception):
    def __init__(self, code: ErrorCode, detail: dict) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class _Net:
    cal: WorkCalendar
    start: date
    data_date: date | None
    acts: dict[str, Activity]
    preds: dict[str, list[Relation]]
    succs: dict[str, list[Relation]]
    order: tuple[str, ...]


def _sides(a: Activity) -> tuple[int, int]:
    """(시작 쪽, 종료 쪽) 이 하루 중 어디인지."""
    if a.kind == "start_ms":
        return _AM, _AM
    if a.kind == "finish_ms":
        return _PM, _PM
    return _AM, _PM


def _duration(a: Activity) -> int:
    """계산에 쓰는 기간. 시작만 한 액티비티는 남은 기간."""
    if a.actual_start and not a.actual_finish and a.rd is not None:
        return a.rd
    return a.od


def _validate(schedule: Schedule) -> None:
    if not schedule.activities:
        raise ScheduleError("empty", {})
    for a in schedule.activities:
        milestone = a.kind != "task"
        if a.od < 0 or (a.od != 0) == milestone or (a.rd is not None and a.rd < 0):
            raise ScheduleError(
                "bad_duration", {"activity": a.id, "kind": a.kind, "od": a.od, "rd": a.rd}
            )
    ids: set[str] = set()
    for a in schedule.activities:
        if a.id in ids:
            raise ScheduleError("duplicate_id", {"activity": a.id})
        ids.add(a.id)
    for r in schedule.relations:
        for ref in (r.pred, r.succ):
            if ref not in ids:
                raise ScheduleError(
                    "dangling_ref", {"pred": r.pred, "succ": r.succ, "missing": ref}
                )


def _topological_order(ids: list[str], relations: tuple[Relation, ...]) -> tuple[str, ...]:
    """선행이 항상 먼저 오는 순서. 동률은 id 순."""
    indegree = dict.fromkeys(ids, 0)
    succs: dict[str, list[str]] = {i: [] for i in ids}
    for r in relations:
        indegree[r.succ] += 1
        succs[r.pred].append(r.succ)
    ready = [i for i in ids if indegree[i] == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        i = heapq.heappop(ready)
        order.append(i)
        for s in succs[i]:
            indegree[s] -= 1
            if indegree[s] == 0:
                heapq.heappush(ready, s)
    if len(order) < len(ids):
        raise ScheduleError("cycle", {"activities": sorted(set(ids) - set(order))})
    return tuple(order)


def _build(schedule: Schedule) -> _Net:
    _validate(schedule)
    acts = {a.id: a for a in schedule.activities}
    preds: dict[str, list[Relation]] = {i: [] for i in acts}
    succs: dict[str, list[Relation]] = {i: [] for i in acts}
    for r in schedule.relations:
        preds[r.succ].append(r)
        succs[r.pred].append(r)
    order = _topological_order(list(acts), schedule.relations)
    cal = WorkCalendar(schedule.calendar)
    return _Net(cal, schedule.start, schedule.data_date, acts, preds, succs, order)


def _lagged(cal: WorkCalendar, d: date, side: int, lag: int) -> date:
    """(d, side) 시점을 꼬리표 없는 달력의 근무일 lag 개만큼 옮긴다. 쪽은 그대로."""
    if lag == 0:
        return d
    if side == _PM:  # 쉬는 날 저녁은 그 앞 근무일 저녁과 같은 시점
        d = cal.prev_workday(d)
    return cal.shift(d, lag)


def _earliest(cal: WorkCalendar, d: date, src: int, dst: int, tags: tuple[str, ...]) -> date:
    """(d, src) 시점 이후에 dst 쪽이 놓일 수 있는 가장 이른 날."""
    if src == _PM and dst == _AM:
        d += _DAY
    return cal.next_workday(d, tags)


def _latest(cal: WorkCalendar, d: date, src: int, dst: int, tags: tuple[str, ...]) -> date:
    """(d, src) 시점 이전에 dst 쪽이 놓일 수 있는 가장 늦은 날."""
    if src == _AM and dst == _PM:
        d -= _DAY
    return cal.prev_workday(d, tags)


def _start_bound(net: _Net, a: Activity, rel: Relation, early: _Dates) -> date:
    """선행 관계 하나가 a 의 시작일에 주는 하한."""
    pred = net.acts[rel.pred]
    end = 0 if rel.type[0] == "S" else 1
    src = _sides(pred)[end]
    d = _lagged(net.cal, early[pred.id][end], src, rel.lag)
    start_side, finish_side = _sides(a)
    if rel.type[1] == "S":
        return _earliest(net.cal, d, src, start_side, a.tags)
    finish = _earliest(net.cal, d, src, finish_side, a.tags)
    return net.cal.add_workdays(finish, -_duration(a), a.tags)


def _late_start(net: _Net, a: Activity, lf: date, early: _Dates) -> date:
    """종료 상한 lf 에 맞는 시작 상한. 실적이 있으면 실제 막대를 여유만큼 통째로 민다."""
    if a.actual_start or a.actual_finish:
        es, ef = early[a.id]
        return net.cal.shift(es, net.cal.workdays_between(ef, lf, a.tags), a.tags)
    return net.cal.add_workdays(lf, -_duration(a), a.tags)


def _late_finish(net: _Net, a: Activity, ls: date, early: _Dates) -> date:
    """시작 상한 ls 에 맞는 종료 상한. _late_start 의 거울."""
    if a.actual_start or a.actual_finish:
        es, ef = early[a.id]
        return net.cal.shift(ef, net.cal.workdays_between(es, ls, a.tags), a.tags)
    return net.cal.add_workdays(ls, _duration(a), a.tags)


def _finish_bound(
    net: _Net, a: Activity, rel: Relation, dates: _Dates, early: _Dates
) -> date:
    """후행 관계 하나가 a 의 종료일에 주는 상한. dates 는 후행들의 (시작, 종료) 날짜."""
    succ = net.acts[rel.succ]
    end = 0 if rel.type[1] == "S" else 1
    src = _sides(succ)[end]
    d = _lagged(net.cal, dates[succ.id][end], src, -rel.lag)
    start_side, finish_side = _sides(a)
    if rel.type[0] == "F":
        return _latest(net.cal, d, src, finish_side, a.tags)
    start = _latest(net.cal, d, src, start_side, a.tags)
    return _late_finish(net, a, start, early)


def _early_dates(net: _Net, a: Activity, early: _Dates) -> tuple[date, date]:
    start_side = _sides(a)[0]
    bounds = [_earliest(net.cal, net.start, _AM, start_side, a.tags)]
    if a.constraint and a.constraint.type == "SNET":
        bounds.append(_earliest(net.cal, a.constraint.date, _AM, start_side, a.tags))
    if a.pinned_start and not a.actual_finish:  # 자원 맞춤이 정한 하한(실적이 있으면 무시)
        bounds.append(_earliest(net.cal, a.pinned_start, _AM, start_side, a.tags))
    if a.start_floor and not a.actual_finish:  # 기록한 지연이 정한 하한(실적이 있으면 무시)
        bounds.append(_earliest(net.cal, a.start_floor, _AM, start_side, a.tags))
    if net.data_date and not a.actual_finish:  # 안 끝난 일은 Data Date 앞에 놓이지 않는다
        bounds.append(_earliest(net.cal, net.data_date, _AM, start_side, a.tags))
    bounds += [_start_bound(net, a, r, early) for r in net.preds[a.id]]
    start = a.actual_start or max(bounds)
    if a.actual_finish:
        return min(start, a.actual_finish), a.actual_finish
    resume = start
    if a.actual_start and net.data_date:  # 남은 일은 Data Date 부터 센다
        resume = net.cal.next_workday(max(start, net.data_date), a.tags)
    return start, net.cal.add_workdays(resume, _duration(a), a.tags)


def _forward(net: _Net) -> _Dates:
    early: _Dates = {}
    for i in net.order:
        early[i] = _early_dates(net, net.acts[i], early)
    return early


def _late_dates(
    net: _Net, a: Activity, late: _Dates, early: _Dates, finish: date
) -> tuple[date, date]:
    finish_side = _sides(a)[1]
    bounds = [_latest(net.cal, finish, _PM, finish_side, a.tags)]
    if a.constraint and a.constraint.type == "FNLT":
        bounds.append(_latest(net.cal, a.constraint.date, _PM, finish_side, a.tags))
    bounds += [_finish_bound(net, a, r, late, early) for r in net.succs[a.id]]
    lf = min(bounds)
    return _late_start(net, a, lf, early), lf


def _backward(net: _Net, early: _Dates, finish: date) -> _Dates:
    late: _Dates = {}
    for i in reversed(net.order):
        late[i] = _late_dates(net, net.acts[i], late, early, finish)
    return late


def _free_float(net: _Net, a: Activity, early: _Dates, finish: date) -> int:
    """후행의 이른 날짜도 사업 종료일도 밀지 않고 늦출 수 있는 근무일 수(음수는 0)."""
    ef = early[a.id][1]
    limits = [_latest(net.cal, finish, _PM, _sides(a)[1], a.tags)]
    limits += [_finish_bound(net, a, r, early, early) for r in net.succs[a.id]]
    return max(0, min(net.cal.workdays_between(ef, d, a.tags) for d in limits))


def _row(net: _Net, a: Activity, early: _Dates, late: _Dates, finish: date) -> CpmRow:
    es, ef = early[a.id]
    ls, lf = late[a.id]
    tf = net.cal.workdays_between(ef, lf, a.tags)
    if a.actual_finish:  # 끝난 액티비티: 늦은 날짜는 실제 날짜로 보여 주고, 여유는 계산값
        ls, lf = es, ef
    return CpmRow(es, ef, ls, lf, tf, _free_float(net, a, early, finish), tf <= 0)


def compute(schedule: Schedule) -> CpmResult:
    net = _build(schedule)
    try:
        return _compute(net)
    except NoWorkdayError as e:
        raise ScheduleError("no_workdays", {"tags": list(e.tags)}) from e


def _compute(net: _Net) -> CpmResult:
    early = _forward(net)
    finish = max(ef for _, ef in early.values())
    late = _backward(net, early, finish)
    rows = {i: _row(net, net.acts[i], early, late, finish) for i in net.order}
    critical_path = tuple(i for i in net.order if rows[i].critical)
    return CpmResult(rows, finish, critical_path)
