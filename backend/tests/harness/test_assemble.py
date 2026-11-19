"""조건 조립(assemble)과 일정에 넣기(apply_to_schedule). 작업 지시서의 시험과 R3·R4·R6 의 시험."""

from dataclasses import replace
from datetime import date

import pytest

from app.core.calendar import KOREA_HOLIDAYS_2027
from app.core.model import (
    Activity,
    BlockedPeriod,
    CalendarSpec,
    Constraint,
    Relation,
    Resource,
)
from app.harness.assemble import apply_to_schedule, assemble
from app.harness.conditions import BASE_RULES, Condition
from tests.schedules import make, task


def cnd(cid: str, layer: str, kind: str, params: dict, **k) -> Condition:
    return Condition(cid, layer, kind, params, "", "프롬프트", **k)


# ── 작업 지시서의 시험 ──────────────────────────────────────────────


def test_input_overrides_domain_same_target():
    d = Condition("d1", "domain", "blocked_period", {"start_md": [12, 15], "end_md": [2, 15], "tag": "타설"}, "", "분야 규칙")
    i = Condition("i1", "input", "blocked_period", {"start_md": [12, 1], "end_md": [2, 28], "tag": "타설"}, "", "프롬프트")
    out = {c.id: c.enabled for c in assemble([d], [], [i])}; assert out == {**{b.id: True for b in BASE_RULES}, "d1": False, "i1": True}


def test_base_cannot_be_disabled():
    hacked = Condition("base.no_cycle", "input", "no_cycle", {}, "", "프롬프트", enabled=False)
    assert next(c for c in assemble([], [], [hacked]) if c.id == "base.no_cycle" and c.layer == "base").enabled


def test_apply_sets_capacity_and_calendar(two_crane_tasks):
    s = apply_to_schedule(two_crane_tasks, [Condition("c", "input", "resource_cap", {"resource_id": "crane", "capacity": 2}, "", "질문지")])
    assert s.resources[0].capacity == 2


# ── R3: 기본 규칙 ───────────────────────────────────────────────────


def test_base_rules():
    assert [(b.id, b.layer, b.kind, b.source, b.enabled) for b in BASE_RULES] == [
        ("base.no_cycle", "base", "no_cycle", "기본 규칙", True),
        ("base.no_dangling", "base", "no_dangling", "기본 규칙", True),
        ("base.calendar", "base", "calendar", "기본 규칙", True),
        ("base.valid", "base", "valid", "기본 규칙", True),
    ]
    assert all(b.text for b in BASE_RULES) and BASE_RULES[3].text == "기간과 ID가 올바름"


def test_base_rules_come_first_and_cannot_be_replaced_by_id_or_layer():
    by_id = cnd("base.calendar", "input", "calendar", {"days_per_week": 6, "holidays": []})
    by_layer = cnd("x", "base", "no_cycle", {}, enabled=False)
    assert assemble([by_layer], [], [by_id]) == list(BASE_RULES)


def test_a_calendar_condition_does_not_compete_with_the_base_calendar_rule():
    calendar = cnd("d.cal", "domain", "calendar", {"days_per_week": 6, "holidays": "KR"})
    out = assemble([calendar], [], [])
    assert out == [*BASE_RULES, calendar]


# ── R4: 같은 종류·같은 대상이면 뒤 겹이 이긴다 ───────────────────────

TARGETED = [
    ("resource_cap", {"resource_id": "crane", "capacity": 1}, {"resource_id": "crane", "capacity": 2},
     {"resource_id": "pump", "capacity": 1}),
    ("milestone_by", {"activity_id": "M1", "date": "2027-05-01"}, {"activity_id": "M1", "date": "2027-04-01"},
     {"activity_id": "M2", "date": "2027-04-01"}),
    ("blocked_period", {"start_md": [12, 15], "end_md": [2, 15], "tag": "타설"},
     {"start_md": [12, 1], "end_md": [2, 28], "tag": "타설"}, {"start_md": [7, 1], "end_md": [7, 31], "tag": "도장"}),
    ("min_gap", {"after_tag": "타설", "days": 7}, {"after_tag": "타설", "days": 5}, {"after_tag": "도장", "days": 1}),
]


@pytest.mark.parametrize(("kind", "first", "same", "other"), TARGETED, ids=[t[0] for t in TARGETED])
def test_same_target_overrides_and_other_target_does_not(kind, first, same, other):
    out = assemble([cnd("d", "domain", kind, first)], [cnd("m", "mine", kind, same)], [cnd("i", "input", kind, other)])
    got = {c.id: (c.enabled, c.overridden_by) for c in out if c.layer != "base"}
    assert got == {"d": (False, "m"), "m": (True, None), "i": (True, None)}


SINGLETONS = [
    ("finish_by", {"date": "2027-12-31"}, {"date": "2027-11-30"}),
    ("start_after", {"date": "2027-03-01"}, {"date": "2027-04-01"}),
    ("calendar", {"days_per_week": 6, "holidays": "KR"}, {"days_per_week": 5, "holidays": []}),
    ("max_duration", {"days": 20}, {"days": 10}),
]


@pytest.mark.parametrize(("kind", "first", "second"), SINGLETONS, ids=[s[0] for s in SINGLETONS])
def test_singleton_kinds_override_whatever_their_params(kind, first, second):
    out = assemble([cnd("d", "domain", kind, first)], [], [cnd("i", "input", kind, second)])
    assert {c.id: (c.enabled, c.overridden_by) for c in out[len(BASE_RULES):]} == {"d": (False, "i"), "i": (True, None)}


@pytest.mark.parametrize("kind", ["text_only", "duration_per_unit"])
def test_unchecked_kinds_never_override_each_other(kind):
    out = assemble([cnd("d", "domain", kind, {})], [cnd("m", "mine", kind, {})], [cnd("i", "input", kind, {})])
    assert all(c.enabled and c.overridden_by is None for c in out)


def test_the_last_one_wins_across_and_within_layers():
    out = assemble(
        [cnd("d", "domain", "finish_by", {"date": "2027-12-31"})],
        [cnd("m", "mine", "finish_by", {"date": "2027-12-15"})],
        [cnd("i1", "input", "finish_by", {"date": "2027-12-01"}), cnd("i2", "input", "finish_by", {"date": "2027-11-30"})],
    )
    got = {c.id: (c.enabled, c.overridden_by) for c in out[len(BASE_RULES):]}
    assert got == {"d": (False, "i2"), "m": (False, "i2"), "i1": (False, "i2"), "i2": (True, None)}


def test_a_condition_switched_off_by_the_user_does_not_override():
    out = assemble(
        [cnd("d", "domain", "finish_by", {"date": "2027-12-31"})],
        [],
        [cnd("i", "input", "finish_by", {"date": "2027-11-30"}, enabled=False)],
    )
    assert {c.id: (c.enabled, c.overridden_by) for c in out[len(BASE_RULES):]} == {"d": (True, None), "i": (False, None)}


def test_reassembling_is_stable_and_frees_a_loser_whose_winner_is_gone():
    d = cnd("d", "domain", "finish_by", {"date": "2027-12-31"})
    i = cnd("i", "input", "finish_by", {"date": "2027-11-30"})
    first = assemble([d], [], [i])
    loser = first[len(BASE_RULES)]
    assert (loser.enabled, loser.overridden_by) == (False, "i")
    assert assemble([loser], [], [i]) == first
    assert assemble([loser], [], [])[len(BASE_RULES):] == [d]


# ── R6: 일정에 넣기 ─────────────────────────────────────────────────

FINISH_BY_0310 = cnd("f", "input", "finish_by", {"date": "2027-03-10"})
FNLT_0310 = Constraint("FNLT", date(2027, 3, 10))


def constraints(schedule) -> dict:
    return {a.id: a.constraint for a in schedule.activities}


def test_finish_by_constrains_the_finish_milestones_only():
    finish = Activity("F", "준공", "finish_ms", "1", 0)
    s = make([task("A", 3), finish, task("C", 1)], [Relation("A", "F")])
    assert constraints(apply_to_schedule(s, [FINISH_BY_0310])) == {"A": None, "F": FNLT_0310, "C": None}


def test_finish_by_without_a_finish_milestone_constrains_activities_without_successors():
    s = make([task("A", 3), task("B", 2), task("C", 1)], [Relation("A", "B")])
    assert constraints(apply_to_schedule(s, [FINISH_BY_0310])) == {"A": None, "B": FNLT_0310, "C": FNLT_0310}


def test_finish_by_keeps_an_earlier_fnlt_and_any_snet_and_replaces_a_later_fnlt():
    earlier = Constraint("FNLT", date(2027, 3, 5))
    snet = Constraint("SNET", date(2027, 3, 2))
    s = make(
        [
            task("A", 1, constraint=earlier),
            task("B", 1, constraint=Constraint("FNLT", date(2027, 3, 20))),
            task("C", 1, constraint=snet),
        ]
    )
    assert constraints(apply_to_schedule(s, [FINISH_BY_0310])) == {"A": earlier, "B": FNLT_0310, "C": snet}


def test_start_after_only_moves_the_start_later(s_finish_0305):
    later = apply_to_schedule(s_finish_0305, [cnd("s", "input", "start_after", {"date": "2027-03-08"})])
    earlier = apply_to_schedule(s_finish_0305, [cnd("s", "input", "start_after", {"date": "2027-02-01"})])
    assert (later.start, earlier.start) == (date(2027, 3, 8), date(2027, 3, 1))


def test_resource_cap_sets_only_that_resource():
    s = make([task("A", 1)], resources=[Resource("crane", "타워크레인", "대", 1), Resource("pump", "펌프카", "대", 1)])
    out = apply_to_schedule(s, [cnd("r", "input", "resource_cap", {"resource_id": "pump", "capacity": 3})])
    assert [(r.id, r.capacity) for r in out.resources] == [("crane", 1), ("pump", 3)]
    unknown = apply_to_schedule(s, [cnd("r", "input", "resource_cap", {"resource_id": "hoist", "capacity": 3})])
    assert unknown == s


def test_calendar_sets_days_and_holidays_and_keeps_blocked_periods():
    winter = BlockedPeriod((12, 1), (2, 28), "타설")
    s = make([task("A", 1)], cal=CalendarSpec(5, (date(2027, 3, 2),), (winter,)))
    kr = apply_to_schedule(s, [cnd("c", "input", "calendar", {"days_per_week": 6, "holidays": "KR"})])
    assert kr.calendar == CalendarSpec(6, KOREA_HOLIDAYS_2027, (winter,))
    none = apply_to_schedule(s, [cnd("c", "input", "calendar", {"days_per_week": 7, "holidays": []})])
    assert none.calendar == CalendarSpec(7, (), (winter,))


def test_blocked_period_is_appended_once():
    s = make([task("A", 1)], cal=CalendarSpec(5, (), (BlockedPeriod((7, 1), (7, 31), "도장"),)))
    winter = cnd("b", "input", "blocked_period", {"start_md": [12, 1], "end_md": [2, 28], "tag": "타설"})
    out = apply_to_schedule(apply_to_schedule(s, [winter]), [winter, replace(winter, id="b2")])
    assert out.calendar.blocked == (BlockedPeriod((7, 1), (7, 31), "도장"), BlockedPeriod((12, 1), (2, 28), "타설"))


def test_disabled_base_and_check_only_conditions_change_nothing(s_finish_0305):
    conditions = [
        *BASE_RULES,
        cnd("f", "input", "finish_by", {"date": "2027-03-04"}, enabled=False),
        cnd("g", "input", "min_gap", {"after_tag": "타설", "days": 7}),
        cnd("x", "input", "max_duration", {"days": 1}),
        cnd("m", "input", "milestone_by", {"activity_id": "A", "date": "2027-03-02"}),
        cnd("t", "input", "text_only", {}),
        cnd("u", "input", "duration_per_unit", {}),
    ]
    assert apply_to_schedule(s_finish_0305, conditions) == s_finish_0305
