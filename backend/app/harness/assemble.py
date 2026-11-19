"""조건 조립(assemble)과, 조건을 일정에 넣기(apply_to_schedule)."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from app.core.calendar import KOREA_HOLIDAYS_2027
from app.core.model import Activity, BlockedPeriod, Constraint, Schedule
from app.harness.conditions import BASE_IDS, BASE_RULES, Condition

# 같은 종류끼리 겨룰 때의 대상 칸. 여기 없는 종류(finish_by·start_after·calendar·max_duration)는
# 일정에 하나만 있는 조건이라 종류만 같아도 겨룬다.
_TARGET_PARAM = {
    "resource_cap": "resource_id",
    "milestone_by": "activity_id",
    "blocked_period": "tag",
    "min_gap": "after_tag",
}
_SINGLETONS = frozenset({"finish_by", "start_after", "calendar", "max_duration"})


def _contest_key(c: Condition) -> tuple[str, str | None] | None:
    """겨루는 열쇠 (kind, 대상). 다른 조건을 이기지도 지지도 않는 종류면 None(text_only 등)."""
    if c.kind in _TARGET_PARAM:
        return c.kind, c.params[_TARGET_PARAM[c.kind]]
    if c.kind in _SINGLETONS:
        return c.kind, None
    return None


def assemble(
    domain_rules: Sequence[Condition], my_rules: Sequence[Condition], inputs: Sequence[Condition]
) -> list[Condition]:
    """BASE_RULES + 분야 규칙 + 내 규칙 + 입력 조건을 하나의 목록으로 묶는다.

    - BASE_RULES 가 맨 앞에 늘 그대로 들어간다. 받은 목록에서 기본 규칙 id 이거나 겹이 "base" 인
      조건은 버린다(기본 규칙은 끄거나 바꿀 수 없다).
    - 켜진 조건끼리 (kind, 대상)이 같으면 나중 것이 이긴다: 인자 순서(분야 < 내 규칙 < 입력),
      같은 겹 안에서는 목록에서 뒤에 있는 것. 진 조건은 enabled=False, overridden_by=이긴 id 로 남는다.
    - 진 표시(overridden_by 가 있는 조건)는 조립할 때마다 새로 매긴다. 이긴 조건이 없어지면 다시 켜진다.
      사용자가 끈 조건(enabled=False, overridden_by=None)은 꺼진 채로 남고 겨루지 않는다.
    """
    rest = [
        replace(c, enabled=c.enabled or c.overridden_by is not None, overridden_by=None)
        for c in (*domain_rules, *my_rules, *inputs)
        if c.id not in BASE_IDS and c.layer != "base"
    ]
    winner: dict[tuple[str, str | None], int] = {}
    for n, c in enumerate(rest):
        key = _contest_key(c)
        if key is not None and c.enabled:
            winner[key] = n
    out = list(BASE_RULES)
    for n, c in enumerate(rest):
        key = _contest_key(c)
        if key is not None and c.enabled and winner[key] != n:
            c = replace(c, enabled=False, overridden_by=rest[winner[key]].id)
        out.append(c)
    return out


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
    spec = replace(s.calendar, days_per_week=params["days_per_week"], holidays=holidays_of(params["holidays"]))
    return replace(s, calendar=spec)


def _blocked_period(s: Schedule, params: dict) -> Schedule:
    period = BlockedPeriod(tuple(params["start_md"]), tuple(params["end_md"]), params["tag"])
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
    """조건을 일정에 넣은 새 일정. 목록 순서대로 넣는다(같은 칸이면 뒤 것이 남는다).

    finish_by → FNLT(종료 마일스톤, 없으면 후행 없는 액티비티) · start_after → Schedule.start(늦어지기만)
    · resource_cap → Resource.capacity · calendar → 근무 요일·공휴일("KR" 은 2027년 자료만 있다)
    · blocked_period → CalendarSpec.blocked 에 덧붙임(같은 것이 있으면 그대로).
    꺼진 조건과 기본 규칙(겹 "base")은 넣지 않는다. min_gap·max_duration·milestone_by·text_only·
    duration_per_unit 은 점검만 하고 넣지 않는다. 여러 번 넣어도 결과가 같다.
    """
    for c in conditions:
        if c.enabled and c.layer != "base" and c.kind in _APPLY:
            schedule = _APPLY[c.kind](schedule, c.params)
    return schedule
