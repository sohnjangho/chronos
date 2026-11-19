"""조건 점검: 일정이 조건을 지키는지 코드로 잰다. 날짜 셈은 전부 app/core 것을 쓴다.

`check(schedule, conditions)` 의 순서
1. 켜진 조건을 일정에 넣는다(`apply_to_schedule`). 꺼진 조건은 어디에도 나오지 않는다.
2. `compute` 뒤 `level(shift=True)`. 날짜 조건은 맞춘 뒤 날짜(화면에 보이는 일정)로 잰다.
3. 양은 모두 조건을 넣은 일정 달력(꼬리표 없음)의 근무일 수다.

보고서
- passed: 위반이 없는 점검 가능 조건(알림이 있어도 통과다). 기본 규칙은 계산이 되면 통과다.
- violations / notices: 조건마다 많아야 하나씩, 조건 순서대로. notices 는 resource_cap 에만 나온다.
- uncheckable: 켜져 있지만 코드로 점검하지 않는 조건(text_only·duration_per_unit). 통과로 치지 않는다.
- skipped: 일정이 계산되지 않아(ScheduleError) 점검하지 못한 조건. 그때 위반은 기본 규칙 하나뿐이다.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from app.core.calendar import WorkCalendar
from app.core.cpm import CpmResult, ScheduleError, compute
from app.core.model import BlockedPeriod, CalendarSpec, Schedule
from app.core.resources import LevelResult, level, usage
from app.harness.assemble import apply_to_schedule, holidays_of
from app.harness.conditions import Condition
from app.store.messages import schedule_error_message


@dataclass(frozen=True)
class Violation:
    condition_id: str
    message: str  # 한국어, 숫자를 담는다
    activity_ids: tuple[str, ...]  # 관련 액티비티(정렬)
    amount: int | None  # 얼마나 어겼는지(근무일·대수). 잴 수 없으면 None


@dataclass(frozen=True)
class CheckReport:
    passed: list[str]
    violations: list[Violation]
    uncheckable: list[str]
    notices: list[Violation] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


# ScheduleError 코드 → 어겨진 기본 규칙
_ERROR_RULE = {
    "cycle": "base.no_cycle",
    "dangling_ref": "base.no_dangling",
    "no_workdays": "base.calendar",
    "bad_duration": "base.valid",
    "empty": "base.valid",
    "duplicate_id": "base.valid",
}

_Usage = dict[str, dict[date, tuple[str, ...]]]


@dataclass(frozen=True)
class _Ctx:
    schedule: Schedule  # 조건을 넣은 일정
    cal: WorkCalendar
    lv: LevelResult  # 맞춘 뒤(화면 날짜). 날짜 조건은 lv.cpm 으로 잰다
    before: _Usage  # 맞추기 전 날짜의 자원 사용
    after: _Usage  # 맞춘 뒤 날짜의 자원 사용


def _context(s: Schedule, cpm: CpmResult) -> _Ctx:
    lv = level(s, cpm, shift=True)
    before = usage(s, {i: (row.es, row.ef) for i, row in cpm.rows.items()})
    return _Ctx(s, WorkCalendar(s.calendar), lv, before, usage(lv.schedule, lv.dates))


def _day(text: str) -> date:
    return date.fromisoformat(text)


# ── 날짜 ────────────────────────────────────────────────────────────


def _finish_by(c: Condition, x: _Ctx) -> Violation | None:
    due, finish = _day(c.params["date"]), x.lv.cpm.finish
    if finish <= due:
        return None
    late = tuple(sorted(i for i, row in x.lv.cpm.rows.items() if row.ef > due))
    days = x.cal.workdays_between(due, finish)
    return Violation(c.id, f"준공이 기한보다 {days}일 늦습니다.", late, days)


def _milestone_by(c: Condition, x: _Ctx) -> Violation | None:
    aid, due = c.params["activity_id"], _day(c.params["date"])
    row = x.lv.cpm.rows.get(aid)
    if row is None:
        return Violation(c.id, "없는 액티비티를 가리킵니다.", (), None)
    if row.ef <= due:
        return None
    days = x.cal.workdays_between(due, row.ef)
    return Violation(c.id, f"{aid} 종료가 기한보다 {days}일 늦습니다.", (aid,), days)


def _start_after(c: Condition, x: _Ctx) -> Violation | None:
    """시작 가능일보다 먼저 놓인 액티비티(실적 등). 양 = 가장 이른 것이 시작 가능일까지 모자란 근무일."""
    allowed = _day(c.params["date"])
    rows = x.lv.cpm.rows
    early = tuple(sorted(i for i, row in rows.items() if row.es < allowed))
    if not early:
        return None
    first = min(rows[i].es for i in early)
    days = x.cal.workdays_between(first, x.cal.next_workday(allowed))
    message = f"시작 가능일보다 먼저 시작하는 액티비티가 {len(early)}개 있습니다(최대 {days}일 이름)."
    return Violation(c.id, message, early, days)


def _max_duration(c: Condition, x: _Ctx) -> Violation | None:
    limit = c.params["days"]
    over = {a.id: a.od - limit for a in x.schedule.activities if a.od > limit}
    if not over:
        return None
    worst = max(over.values())
    message = f"기간이 {limit}일을 넘는 액티비티가 {len(over)}개 있습니다(최대 {worst}일 초과)."
    return Violation(c.id, message, tuple(sorted(over)), worst)


def _min_gap(c: Condition, x: _Ctx) -> Violation | None:
    """꼬리표가 붙은 선행의 종료와 후행 시작 사이 근무일(workdays_between)이 days 보다 작은 곳."""
    tag, need = c.params["after_tag"], c.params["days"]
    rows = x.lv.cpm.rows
    tagged = {a.id for a in x.schedule.activities if tag in a.tags}
    short = {}
    for r in x.schedule.relations:
        if r.pred in tagged:
            gap = x.cal.workdays_between(rows[r.pred].ef, rows[r.succ].es)
            if gap < need:
                short[r.pred, r.succ] = gap
    if not short:
        return None
    worst = need - min(short.values())
    ids = tuple(sorted({i for pair in short for i in pair}))
    message = f"'{tag}' 뒤 간격이 {need}일보다 짧은 곳이 {len(short)}곳 있습니다(최대 {worst}일 부족)."
    return Violation(c.id, message, ids, worst)


def _blocked_period(c: Condition, x: _Ctx) -> Violation | None:
    """지킴 확인: 꼬리표가 붙은 액티비티의 시작일이나 종료일이 금지 기간 안(실적이 있을 때만 생긴다).

    금지 기간을 넣은 달력에서는 그 사이 날에 일하지 않으므로, 기간을 건너 쉬었다 이어지는 것은 괜찮다.
    """
    period = BlockedPeriod(tuple(c.params["start_md"]), tuple(c.params["end_md"]), c.params["tag"])
    # 주 7일·공휴일 없음 + 이 기간만 막은 달력: 꼬리표가 있으면 쉬는 날 = 금지 기간 안
    only_period = WorkCalendar(CalendarSpec(7, (), (period,)))
    tags = (period.tag,)
    rows = x.lv.cpm.rows
    inside = tuple(
        sorted(
            a.id
            for a in x.schedule.activities
            if period.tag in a.tags
            and not all(only_period.is_workday(d, tags) for d in (rows[a.id].es, rows[a.id].ef))
        )
    )
    if not inside:
        return None
    return Violation(c.id, f"'{period.tag}' 금지 기간에 일하는 액티비티가 {len(inside)}개 있습니다.", inside, None)


def _calendar(c: Condition, x: _Ctx) -> Violation | None:
    """지킴 확인: 일정 달력이 이 조건의 근무 요일과 공휴일을 쓰는가(같은 목록의 다른 달력 조건에 덮였으면 아니다)."""
    spec, days = x.schedule.calendar, c.params["days_per_week"]
    if spec.days_per_week == days and set(holidays_of(c.params["holidays"])) <= set(spec.holidays):
        return None
    return Violation(c.id, f"달력이 조건(주 {days}일 근무)과 다릅니다.", (), None)


# ── 자원 ────────────────────────────────────────────────────────────


def _over_capacity(c: Condition, x: _Ctx, used: _Usage, prefix: str) -> Violation | None:
    rid = c.params["resource_id"]
    resource = next(r for r in x.schedule.resources if r.id == rid)
    over = {d: ids for d, ids in used.get(rid, {}).items() if len(ids) > resource.capacity}
    if not over:
        return None
    worst = max(len(ids) for ids in over.values()) - resource.capacity
    ids = tuple(sorted({i for day in over.values() for i in day}))
    unit, name, cap = resource.unit, resource.name, resource.capacity
    message = f"{prefix} {name} 필요량이 용량({cap}{unit})을 넘는 날이 {len(over)}일 있습니다(최대 {worst}{unit} 초과)."
    return Violation(c.id, message, ids, worst)


def _has_resource(c: Condition, x: _Ctx) -> bool:
    return any(r.id == c.params["resource_id"] for r in x.schedule.resources)


def _resource_cap(c: Condition, x: _Ctx) -> Violation | None:
    """맞춘 뒤에도 남은 겹침만 위반이다(용량 0, 자리 찾기 한도 초과 등)."""
    if not _has_resource(c, x):
        return Violation(c.id, "없는 자원을 가리킵니다.", (), None)
    return _over_capacity(c, x, x.after, "맞춘 뒤에도")


def _resource_notice(c: Condition, x: _Ctx) -> Violation | None:
    """맞추기 전 날짜의 겹침. 위반이 아니다(맞춤이 일을 미뤄 푼다)."""
    if not _has_resource(c, x):
        return None
    return _over_capacity(c, x, x.before, "맞추기 전 날짜로는")


def _structural(c: Condition, x: _Ctx) -> Violation | None:
    """기본 규칙 종류: 계산이 됐으면 지켜졌다."""
    return None


_CHECKS = {
    "no_cycle": _structural,
    "no_dangling": _structural,
    "valid": _structural,
    "calendar": _calendar,
    "finish_by": _finish_by,
    "start_after": _start_after,
    "milestone_by": _milestone_by,
    "resource_cap": _resource_cap,
    "blocked_period": _blocked_period,
    "min_gap": _min_gap,
    "max_duration": _max_duration,
}


def _error_ids(e: ScheduleError) -> tuple[str, ...]:
    d = e.detail
    if "activities" in d:
        return tuple(sorted(d["activities"]))
    if "activity" in d:
        return (d["activity"],)
    if "missing" in d:
        return tuple(sorted({d["pred"], d["succ"]} - {d["missing"]}))
    return ()


def _broken(e: ScheduleError, checkable: list[Condition], uncheckable: list[str]) -> CheckReport:
    rule = _ERROR_RULE[e.code]
    violation = Violation(rule, schedule_error_message(e), _error_ids(e), None)
    skipped = [c.id for c in checkable if c.id != rule]
    return CheckReport(passed=[], violations=[violation], uncheckable=uncheckable, skipped=skipped)


def check(schedule: Schedule, conditions: Sequence[Condition]) -> CheckReport:
    """일정을 조건으로 점검한다. 일정이 깨졌어도 예외를 내지 않는다(모듈 설명글 참고)."""
    active = [c for c in conditions if c.enabled]
    uncheckable = [c.id for c in active if not c.checkable]
    checkable = [c for c in active if c.checkable]
    s = apply_to_schedule(schedule, active)
    try:
        cpm = compute(s)
    except ScheduleError as e:
        return _broken(e, checkable, uncheckable)
    x = _context(s, cpm)
    report = CheckReport(passed=[], violations=[], uncheckable=uncheckable)
    for c in checkable:
        violation = None if c.layer == "base" else _CHECKS[c.kind](c, x)
        if violation is None:
            report.passed.append(c.id)
        else:
            report.violations.append(violation)
        notice = _resource_notice(c, x) if c.kind == "resource_cap" else None
        if notice is not None:
            report.notices.append(notice)
    return report
