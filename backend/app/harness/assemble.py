"""조건 조립(assemble), 조건을 일정에 넣기(apply_to_schedule), 그리고 둘을 잇는 준비(prepare).

화면(app.store 의 run·view)과 점검(check)은 같은 `prepare` 를 거친 일정을 계산한다.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date, timedelta

from app.core.calendar import KOREA_HOLIDAYS_2027, WorkCalendar
from app.core.model import Activity, BlockedPeriod, CalendarSpec, Constraint, Schedule
from app.harness.conditions import (
    BASE_IDS,
    BASE_RULES,
    Condition,
    condition_problem,
    read_conditions,
)

# 같은 대상을 두고 겨루는 종류와 그 대상 칸. blocked_period 는 따로(꼬리표가 같고 기간이 겹칠 때).
_TARGET_PARAM = {"resource_cap": "resource_id", "milestone_by": "activity_id", "min_gap": "after_tag"}
# 일정에 하나만 있는 조건: 종류만 같아도 겨룬다.
_SINGLETONS = frozenset({"finish_by", "start_after", "calendar", "max_duration"})
_COMPETING = frozenset({*_TARGET_PARAM, *_SINGLETONS, "blocked_period"})
# 윤년 한 해: 해마다 되풀이되는 기간이 겹치는지 2월 29일까지 넣어 본다.
_ONE_YEAR = tuple(date(2028, 1, 1) + timedelta(days=n) for n in range(366))


def in_period(period: BlockedPeriod, day: date) -> bool:
    """day 가 금지 기간 안인가. core 달력과 같은 규칙(해마다 되풀이, 시작이 끝보다 늦으면 해를 넘김)."""
    only_period = WorkCalendar(CalendarSpec(7, (), (period,)))  # 주 7일·공휴일 없음 + 이 기간만 막음
    return not only_period.is_workday(day, (period.tag,))


def period_of(params: dict) -> BlockedPeriod:
    return BlockedPeriod(tuple(params["start_md"]), tuple(params["end_md"]), params["tag"])


def _covered(params: dict) -> set[date]:
    """윤년 한 해 가운데 그 금지 기간에 드는 날."""
    period = period_of(params)
    only_period = WorkCalendar(CalendarSpec(7, (), (period,)))
    return {d for d in _ONE_YEAR if not only_period.is_workday(d, (period.tag,))}


def _overlap(a: dict, b: dict) -> bool:
    return not _covered(a).isdisjoint(_covered(b))


def _conflict(c: Condition, d: Condition) -> bool:
    """c 와 d 가 같은 것을 두고 겨루는가(둘 다 형식이 맞는 조건)."""
    if c.kind != d.kind or c.kind not in _COMPETING:
        return False
    if c.kind == "blocked_period":
        return c.params["tag"] == d.params["tag"] and _overlap(c.params, d.params)
    if c.kind in _TARGET_PARAM:
        key = _TARGET_PARAM[c.kind]
        return c.params[key] == d.params[key]
    return True


def _competes(c: Condition) -> bool:
    return c.enabled and c.kind in _COMPETING and condition_problem(c) is None


def _reset(c: Condition) -> Condition:
    """진 표시를 지운다(다시 겨룬다). 형식이 틀린 조건은 그대로 둔다."""
    if condition_problem(c) is not None:
        return c
    return replace(c, enabled=c.enabled or c.overridden_by is not None, overridden_by=None)


def _winner(entries: list[tuple[int, Condition]], n: int) -> Condition | None:
    """n 번째 조건을 이기는 조건 가운데 가장 나중 것. 없으면 None.

    뒤에 있는 조건만 이길 수 있다: 겹이 더 뒤이거나, 같은 겹 안에서 목록이 더 뒤(blocked_period 는 제외).
    """
    rank, c = entries[n]
    if not _competes(c):
        return None
    best = None
    for later_rank, d in entries[n + 1:]:
        beats = later_rank > rank or c.kind != "blocked_period"
        if beats and _competes(d) and _conflict(c, d):
            best = d
    return best


def assemble(
    domain_rules: Sequence[Condition], my_rules: Sequence[Condition], inputs: Sequence[Condition]
) -> list[Condition]:
    """BASE_RULES + 분야 규칙 + 내 규칙 + 입력 조건을 하나의 목록으로 묶는다. 예외를 내지 않는다.

    - BASE_RULES 가 맨 앞에 늘 그대로 들어간다. 받은 목록에서 기본 규칙 id 인 조건은 버린다.
    - 같은 id 가 여러 번 있으면 마지막 것만 남긴다(인자 순서로 이어 붙인 목록에서).
    - 켜져 있고 형식이 맞는 조건끼리 겨룬다. 열쇠: resource_cap·milestone_by·min_gap 은 (종류, 대상),
      finish_by·start_after·calendar·max_duration 은 종류만, blocked_period 는 꼬리표가 같고 기간이 겹칠 때.
      나중 것이 이긴다: 인자 순서(분야 < 내 규칙 < 입력), 같은 겹 안에서는 목록에서 뒤에 있는 것.
      다만 blocked_period 는 같은 겹 안에서는 서로 덮지 않는다(철마다 따로 둘 수 있다).
    - 진 조건은 enabled=False, overridden_by=이긴 것 가운데 가장 나중 것의 id 로 남는다.
    - 진 표시(overridden_by)는 조립할 때마다 새로 매긴다. 이긴 조건이 없어지면 다시 켜진다.
      사용자가 끈 조건(enabled=False, overridden_by=None)은 꺼진 채로 남고 겨루지 않는다.
    - 형식이 틀린 조건(condition_problem)은 겨루지 않고 받은 그대로 남는다(겹 "base" 인 다른 id 포함).
    """
    entries = [
        (rank, c)
        for rank, group in enumerate((domain_rules, my_rules, inputs))
        for c in group
        if c.id not in BASE_IDS
    ]
    last = {c.id: n for n, (_, c) in enumerate(entries)}
    entries = [(rank, _reset(c)) for n, (rank, c) in enumerate(entries) if last[c.id] == n]
    out = list(BASE_RULES)
    for n, (_, c) in enumerate(entries):
        winner = _winner(entries, n)
        out.append(c if winner is None else replace(c, enabled=False, overridden_by=winner.id))
    return out


def assemble_all(conditions: Sequence[Condition]) -> list[Condition]:
    """한 목록을 겹으로 나눠 assemble 한다: domain → mine → 그 밖(input, 겹이 틀린 것)."""
    domain = [c for c in conditions if c.layer == "domain"]
    mine = [c for c in conditions if c.layer == "mine"]
    rest = [c for c in conditions if c.layer not in ("domain", "mine")]
    return assemble(domain, mine, rest)


def holidays_of(value: str | list) -> tuple[date, ...]:
    """calendar 조건의 holidays 값 → 공휴일. "KR" 은 대한민국 공휴일(지금은 2027년 자료만 있다)."""
    if value == "KR":
        return KOREA_HOLIDAYS_2027
    return tuple(date.fromisoformat(d) for d in value)


def _with_fnlt(a: Activity, due: date) -> Activity:
    """FNLT 를 건다. 이미 있는 조건은 더 늦은 FNLT 일 때만 바꾼다(SNET 은 그대로 둔다)."""
    if a.constraint is None or (a.constraint.type == "FNLT" and a.constraint.date > due):
        return replace(a, constraint=Constraint("FNLT", due))
    return a


def _finish_by(s: Schedule, params: dict) -> Schedule:
    """종료 마일스톤마다, 없으면 후행이 없는 액티비티마다 FNLT."""
    due = date.fromisoformat(params["date"])
    targets = {a.id for a in s.activities if a.kind == "finish_ms"}
    if not targets:
        has_successor = {r.pred for r in s.relations}
        targets = {a.id for a in s.activities if a.id not in has_successor}
    acts = tuple(_with_fnlt(a, due) if a.id in targets else a for a in s.activities)
    return replace(s, activities=acts)


def _start_after(s: Schedule, params: dict) -> Schedule:
    return replace(s, start=max(s.start, date.fromisoformat(params["date"])))


def _resource_cap(s: Schedule, params: dict) -> Schedule:
    rid, capacity = params["resource_id"], params["capacity"]
    resources = tuple(replace(r, capacity=capacity) if r.id == rid else r for r in s.resources)
    return replace(s, resources=resources)


def _calendar(s: Schedule, params: dict) -> Schedule:
    """근무 요일은 바꾸고, 공휴일은 일정에 있던 것과 합친다(날짜 순)."""
    holidays = tuple(sorted({*s.calendar.holidays, *holidays_of(params["holidays"])}))
    spec = replace(s.calendar, days_per_week=params["days_per_week"], holidays=holidays)
    return replace(s, calendar=spec)


def _blocked_period(s: Schedule, params: dict) -> Schedule:
    period = period_of(params)
    if period in s.calendar.blocked:
        return s
    return replace(s, calendar=replace(s.calendar, blocked=(*s.calendar.blocked, period)))


_APPLY = {
    "finish_by": _finish_by,
    "start_after": _start_after,
    "resource_cap": _resource_cap,
    "calendar": _calendar,
    "blocked_period": _blocked_period,
}


def apply_to_schedule(schedule: Schedule, conditions: Sequence[Condition]) -> Schedule:
    """조건을 일정에 넣은 새 일정. 목록 순서대로 넣는다(같은 칸이면 뒤 것이 남는다). 조립은 하지 않는다.

    finish_by → FNLT(종료 마일스톤, 없으면 후행 없는 액티비티. 더 늦은 FNLT 만 바꾸고 SNET 은 그대로)
    · start_after → Schedule.start(늦어지기만) · resource_cap → Resource.capacity
    · calendar → 근무 요일, 공휴일은 합침("KR" 은 2027년 자료만 있다)
    · blocked_period → CalendarSpec.blocked 에 덧붙임(같은 것이 있으면 그대로).
    꺼진 조건, 기본 규칙 id 인 조건, 형식이 틀린 조건은 넣지 않는다. min_gap·max_duration·milestone_by·
    text_only·duration_per_unit 은 점검만 하고 넣지 않는다. 여러 번 넣어도 결과가 같다.
    """
    for c in conditions:
        if c.enabled and c.kind in _APPLY and c.id not in BASE_IDS and condition_problem(c) is None:
            schedule = _APPLY[c.kind](schedule, c.params)
    return schedule


def prepare(schedule: Schedule, conditions: Sequence[Condition]) -> Schedule:
    """화면과 점검이 같이 쓰는 준비: 기본 규칙과 함께 조립(assemble_all)하고, 켜진 조건을 넣는다.

    형식이 틀린 조건과 진 조건은 넣지 않는다. 넣을 것이 없으면 받은 일정 그대로(같은 객체)다.
    """
    return apply_to_schedule(schedule, assemble_all(conditions))


def prepare_stored(schedule: Schedule, stored: Sequence[object]) -> Schedule:
    """저장된 조건 dict 목록으로 prepare. 읽지 못한 dict 는 건너뛴다."""
    return prepare(schedule, read_conditions(stored)[0])
