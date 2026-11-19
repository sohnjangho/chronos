from dataclasses import replace
from datetime import date

from app.core import resources
from app.core.cpm import compute
from app.core.model import Activity, BlockedPeriod, CalendarSpec, Relation, Resource
from app.core.resources import Peak, level
from tests.core.helpers import act, sched

R = Resource("crane", "타워크레인", "대", 1)
def test_two_tasks_one_crane_are_serialized():
    s = replace(sched([act("A", 3, resources=("crane",)), act("B", 2, resources=("crane",))], []), resources=(R,))
    r = level(s, compute(s))
    assert r.dates["A"] == (date(2027, 3, 1), date(2027, 3, 3)) and r.dates["B"][0] == date(2027, 3, 4)
    assert r.shifted == ("B",) and r.overloads == ()
def test_capacity_two_keeps_them_parallel():
    s = replace(sched([act("A", 3, resources=("crane",)), act("B", 2, resources=("crane",))], []), resources=(replace(R, capacity=2),))
    assert level(s, compute(s)).shifted == ()
def test_check_only_reports_overload_without_moving():
    s = replace(sched([act("A", 3, resources=("crane",)), act("B", 2, resources=("crane",))], []), resources=(R,))
    r = level(s, compute(s), shift=False)
    assert r.dates["B"][0] == date(2027, 3, 1) and r.overloads[0].need == 2 and r.peaks["crane"].need == 2
def test_shift_pushes_successor():
    s = replace(sched([act("A", 3, resources=("crane",)), act("B", 2, resources=("crane",)), act("C", 1)], [Relation("B", "C")]), resources=(R,))
    assert level(s, compute(s)).dates["C"][0] == date(2027, 3, 8)
def test_zero_capacity_does_not_loop():                      # Review Focus 5
    s = replace(sched([act("A", 1, resources=("crane",))], []), resources=(replace(R, capacity=0),))
    r = level(s, compute(s)); assert r.overloads and r.dates["A"][0] == date(2027, 3, 1)
def test_unknown_resource_id_is_ignored():
    s = sched([act("A", 1, resources=("ghost",))], []); assert level(s, compute(s)).overloads == ()


# ---- 추가 시험 (조정자 결정 1~7) ----

def crane(i, od, **k):
    return act(i, od, resources=("crane",), **k)


def with_res(s, *res):
    return replace(s, resources=res or (R,))


def test_result_shape_after_serializing():
    s = with_res(sched([crane("A", 3), crane("B", 2)], []))
    r = level(s, compute(s))
    assert r.dates["B"] == (date(2027, 3, 4), date(2027, 3, 5))
    assert r.finish == date(2027, 3, 5)
    assert r.peaks == {"crane": Peak("crane", date(2027, 3, 1), 1, 1)}


def test_check_only_lists_every_overloaded_day_and_earliest_peak():
    s = with_res(sched([crane("A", 3), crane("B", 2)], []))
    r = level(s, compute(s), shift=False)
    assert r.overloads == (
        Peak("crane", date(2027, 3, 1), 2, 1),
        Peak("crane", date(2027, 3, 2), 2, 1),
    )
    assert r.peaks["crane"].when == date(2027, 3, 1)
    assert r.shifted == () and r.finish == date(2027, 3, 3)


def test_three_tasks_capacity_two_third_waits():
    s = with_res(sched([crane("A", 3), crane("B", 3), crane("C", 2)], []), replace(R, capacity=2))
    r = level(s, compute(s))
    assert r.dates["A"][0] == r.dates["B"][0] == date(2027, 3, 1)
    assert r.dates["C"] == (date(2027, 3, 4), date(2027, 3, 5))
    assert r.shifted == ("C",) and r.overloads == ()
    assert r.peaks["crane"] == Peak("crane", date(2027, 3, 1), 2, 2)


def test_priority_is_early_start_then_small_float_then_id():
    # 같은 날 시작: X 는 뒤에 Y(3일)가 붙어 여유가 0, A 는 여유가 있다 → id 가 늦어도 X 가 먼저.
    s = with_res(sched([crane("A", 2), crane("X", 2), act("Y", 3)], [Relation("X", "Y")]))
    r = level(s, compute(s))
    assert r.dates["X"][0] == date(2027, 3, 1) and r.dates["A"][0] == date(2027, 3, 3)
    assert r.shifted == ("A",)


def test_shift_skips_weekend_and_keeps_duration():
    s = with_res(sched([crane("A", 4), crane("B", 3)], []))
    r = level(s, compute(s))
    assert r.dates["B"] == (date(2027, 3, 5), date(2027, 3, 9))     # 금 → 월·화
    assert r.overloads == ()


def test_successor_relations_hold_after_shift():
    # B 가 밀리면 SS+1 인 C, FF 인 D 도 관계대로 따라간다.
    s = with_res(sched(
        [crane("A", 3), crane("B", 2), act("C", 1), act("D", 1)],
        [Relation("B", "C", "SS", 1), Relation("B", "D", "FF", 0)],
    ))
    r = level(s, compute(s))
    assert r.dates["B"] == (date(2027, 3, 4), date(2027, 3, 5))
    assert r.dates["C"][0] == date(2027, 3, 5) and r.dates["D"][1] == date(2027, 3, 5)
    assert r.finish == date(2027, 3, 5)
    assert r.shifted == ("B", "C", "D")          # 따라 밀린 후행도 넣는다


def test_pushed_successor_is_leveled_at_its_new_dates():
    # B 가 밀리면서 후행 C(크레인)가 D(크레인)와 겹치게 된다 → 다시 맞춘다.
    s = with_res(sched(
        [crane("A", 3), crane("B", 2), crane("C", 2), crane("D", 2)],
        [Relation("B", "C"), Relation("A", "D", "FS", 2)],
    ))
    r = level(s, compute(s))
    days = [d for i in "ABCD" for d in _span(r.dates[i])]
    assert len(days) == len(set(days)) and r.overloads == ()
    assert r.dates["C"][0] > r.dates["B"][1] and r.dates["D"][0] >= date(2027, 3, 8)


def _span(se):
    return [date.fromordinal(o) for o in range(se[0].toordinal(), se[1].toordinal() + 1) if date.fromordinal(o).weekday() < 5]


def test_activity_with_actual_dates_is_never_shifted():
    # A 는 3/2 에 시작했다(3/2~3/4). 우선순위는 B 가 앞서지만 A 는 못 옮기므로 B 가 비킨다.
    s = with_res(sched([crane("A", 3, actual_start=date(2027, 3, 2)), crane("B", 2)], []))
    r = level(s, compute(s))
    assert r.dates["A"] == (date(2027, 3, 2), date(2027, 3, 4))
    assert r.dates["B"] == (date(2027, 3, 5), date(2027, 3, 8))
    assert r.shifted == ("B",) and r.overloads == ()


def test_two_actual_activities_overlap_is_reported_not_moved():
    a = crane("A", 3, actual_start=date(2027, 3, 1))
    b = crane("B", 2, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 2), progress=1.0)
    s = with_res(sched([a, b], []))
    r = level(s, compute(s))
    assert r.shifted == () and r.dates["B"] == (date(2027, 3, 1), date(2027, 3, 2))
    assert [p.when for p in r.overloads] == [date(2027, 3, 1), date(2027, 3, 2)]


def test_milestone_never_consumes_resource():
    m = Activity("M", "M", "start_ms", "1", 0, resources=("crane",))
    s = with_res(sched([crane("A", 2), m], []))
    r = level(s, compute(s))
    assert r.shifted == () and r.overloads == ()
    assert r.peaks["crane"].need == 1
    only = with_res(sched([act("A", 2), m], []))
    assert level(only, compute(only)).peaks == {}


def test_non_workdays_consume_nothing():
    # A 는 금~월(주말 낌). 토·일에는 크레인을 쓰지 않는다.
    s = with_res(sched([crane("A", 2)], [], start=date(2027, 3, 5)))
    r = level(s, compute(s), shift=False)
    assert r.dates["A"] == (date(2027, 3, 5), date(2027, 3, 8))
    assert r.peaks["crane"] == Peak("crane", date(2027, 3, 5), 1, 1)


def test_consumption_follows_the_activitys_own_tagged_calendar():
    # A 는 타설 금지 기간(3/2~3/3)을 건너뛰어 3/1, 3/4 에 일한다. B 는 그 사이 3/2~3/3 에 들어간다.
    cal = CalendarSpec(7, blocked=(BlockedPeriod((3, 2), (3, 3), "타설"),))
    s = with_res(sched([crane("A", 2, tags=("타설",)), crane("B", 2)], [], cal))
    r = level(s, compute(s))
    assert r.dates["A"] == (date(2027, 3, 1), date(2027, 3, 4))
    assert r.dates["B"] == (date(2027, 3, 2), date(2027, 3, 3))
    assert r.shifted == ("B",) and r.overloads == ()


def test_search_bound_leaves_activity_and_reports_overload(monkeypatch):
    # A 는 이미 시작해 30일을 차지한다. 한도를 2일로 줄이면 B 가 들어갈 자리를 못 찾는다.
    monkeypatch.setattr(resources, "MAX_SHIFT_DAYS", 2)
    s = with_res(sched([crane("A", 30, actual_start=date(2027, 3, 1)), crane("B", 2)], []))
    r = level(s, compute(s))
    assert r.dates["B"] == (date(2027, 3, 1), date(2027, 3, 2)) and r.shifted == ()
    assert [p.when for p in r.overloads] == [date(2027, 3, 1), date(2027, 3, 2)]


def test_default_bound_finds_slot_after_long_blocker():
    s = with_res(sched([crane("A", 30, actual_start=date(2027, 3, 1)), crane("B", 2)], []))
    r = level(s, compute(s))
    assert r.dates["B"][0] == date(2027, 4, 12) and r.overloads == ()


def test_zero_capacity_user_stays_and_others_still_level():
    zero = Resource("pump", "펌프카", "대", 0)
    s = with_res(sched([act("A", 2, resources=("pump", "crane")), crane("B", 2)], []), R, zero)
    r = level(s, compute(s))
    assert r.dates["A"][0] == date(2027, 3, 1) and r.dates["B"][0] == date(2027, 3, 3)
    assert {p.resource_id for p in r.overloads} == {"pump"} and r.shifted == ("B",)


def test_two_resources_both_respected():
    hoist = Resource("hoist", "호이스트", "대", 1)
    s = with_res(sched(
        [crane("A", 2), act("B", 2, resources=("hoist",)), act("C", 1, resources=("crane", "hoist"))], [],
    ), R, hoist)
    r = level(s, compute(s))
    assert r.dates["C"][0] == date(2027, 3, 3) and r.shifted == ("C",)
    assert set(r.peaks) == {"crane", "hoist"} and r.overloads == ()


def test_leveling_is_deterministic_regardless_of_input_order():
    acts = [crane("A", 3), crane("B", 2), crane("C", 2), act("D", 1)]
    rels = [Relation("C", "D")]
    s1 = with_res(sched(acts, rels))
    s2 = with_res(sched(list(reversed(acts)), rels))
    r1, r2 = level(s1, compute(s1)), level(s2, compute(s2))
    assert r1 == level(s1, compute(s1))
    assert r1.dates == r2.dates and r1.shifted == r2.shifted
