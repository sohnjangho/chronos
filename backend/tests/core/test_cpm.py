from datetime import date

import pytest

from app.core.cpm import ScheduleError, compute
from app.core.model import (
    Activity,
    BlockedPeriod,
    CalendarSpec,
    Constraint,
    Relation,
    Schedule,
    WbsNode,
)

CAL5 = CalendarSpec(days_per_week=5)
def act(i, od, **k): return Activity(id=i, name=i, kind="task", wbs="1", od=od, **k)
def sched(acts, rels, cal=CAL5, start=date(2027, 3, 1)):
    return Schedule(start=start, calendar=cal, wbs=(WbsNode("1", "w", None),), activities=tuple(acts), relations=tuple(rels))

def test_fs_chain():
    r = compute(sched([act("A", 3), act("B", 2)], [Relation("A", "B")]))
    assert (r.rows["A"].es, r.rows["A"].ef) == (date(2027, 3, 1), date(2027, 3, 3))
    assert (r.rows["B"].es, r.rows["B"].ef) == (date(2027, 3, 4), date(2027, 3, 5))
    assert r.finish == date(2027, 3, 5) and r.critical_path == ("A", "B")
def test_weekend_is_skipped():
    r = compute(sched([act("A", 5), act("B", 1)], [Relation("A", "B")]))
    assert r.rows["B"].es == date(2027, 3, 8)
def test_float_on_parallel_branch():
    r = compute(sched([act("A", 5), act("B", 2), act("C", 1)], [Relation("A", "C"), Relation("B", "C")]))
    assert r.rows["B"].tf == 3 and not r.rows["B"].critical and r.rows["A"].critical
def test_ss_with_lag():
    r = compute(sched([act("A", 5), act("B", 2)], [Relation("A", "B", "SS", 2)]))
    assert r.rows["B"].es == date(2027, 3, 3)
def test_ff_and_sf():
    r = compute(sched([act("A", 5), act("B", 2)], [Relation("A", "B", "FF", 0)]))
    assert r.rows["B"].ef == date(2027, 3, 5)
def test_milestone_zero_duration():
    r = compute(sched([act("A", 3), Activity("M", "M", "finish_ms", "1", 0)], [Relation("A", "M")]))
    assert r.rows["M"].es == r.rows["M"].ef == date(2027, 3, 3)
def test_start_on_holiday_moves_to_next_workday():          # Review Focus 5
    cal = CalendarSpec(5, holidays=(date(2027, 3, 1),))
    assert compute(sched([act("A", 1)], [], cal)).rows["A"].es == date(2027, 3, 2)
def test_blocked_period_applies_only_to_tagged():
    cal = CalendarSpec(7, blocked=(BlockedPeriod((3, 1), (3, 7), "타설"),))
    r = compute(sched([act("A", 1, tags=("타설",)), act("B", 1)], [], cal))
    assert r.rows["A"].es == date(2027, 3, 8) and r.rows["B"].es == date(2027, 3, 1)
def test_fnlt_gives_negative_float():
    a = act("A", 10, constraint=Constraint("FNLT", date(2027, 3, 5)))
    assert compute(sched([a], [])).rows["A"].tf == -5
def test_actual_finish_later_than_plan_pushes_successor():
    a = act("A", 3, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 5), progress=1.0)
    assert compute(sched([a, act("B", 1)], [Relation("A", "B")])).rows["B"].es == date(2027, 3, 8)
def test_actual_earlier_than_plan_is_accepted():             # Review Focus 5
    a = act("A", 3, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 2), progress=1.0)
    assert compute(sched([a, act("B", 1)], [Relation("A", "B")])).rows["B"].es == date(2027, 3, 3)
@pytest.mark.parametrize("rels,code", [([Relation("A", "B"), Relation("B", "A")], "cycle"), ([Relation("A", "Z")], "dangling_ref")])
def test_bad_graph_raises(rels, code):
    with pytest.raises(ScheduleError) as e: compute(sched([act("A", 1), act("B", 1)], rels))
    assert e.value.code == code
def test_negative_duration_raises():
    with pytest.raises(ScheduleError) as e: compute(sched([act("A", -1)], []))
    assert e.value.code == "bad_duration"


# ---- 추가 시험 (조정자 결정 1·2·3·4·7·8) ----

def ms(i, kind):
    return Activity(i, i, kind, "1", 0)


def test_sf_successor_finishes_on_or_after_predecessor_start():
    r = compute(sched([act("A", 5), act("B", 2)], [Relation("A", "B", "SF", 0)]))
    assert r.rows["B"].ef >= r.rows["A"].es


def test_sf_with_lag_binds_successor_finish():
    r = compute(sched([act("A", 5), act("B", 2)], [Relation("A", "B", "SF", 4)]))
    assert (r.rows["B"].es, r.rows["B"].ef) == (date(2027, 3, 4), date(2027, 3, 5))


def test_fs_with_lag_counts_workdays():
    r = compute(sched([act("A", 3), act("B", 2)], [Relation("A", "B", "FS", 2)]))
    assert r.rows["B"].es == date(2027, 3, 8)          # EF 3/3(수) + 2일 → 3/5, 그 다음 근무일


def test_fs_with_negative_lag_overlaps():
    r = compute(sched([act("A", 5), act("B", 2)], [Relation("A", "B", "FS", -2)]))
    assert r.rows["B"].es == date(2027, 3, 4)          # EF 3/5 − 2일 → 3/3, 그 다음 근무일


def test_ss_with_negative_lag_is_bounded_by_project_start():
    r = compute(sched([act("X", 2), act("A", 5), act("B", 2)], [Relation("X", "A"), Relation("A", "B", "SS", -1)]))
    assert r.rows["A"].es == date(2027, 3, 3) and r.rows["B"].es == date(2027, 3, 2)
    r = compute(sched([act("A", 5), act("B", 2)], [Relation("A", "B", "SS", -1)]))
    assert r.rows["B"].es == date(2027, 3, 1)


def test_ff_with_lag_derives_start_from_duration():
    r = compute(sched([act("A", 5), act("B", 2)], [Relation("A", "B", "FF", 1)]))
    assert (r.rows["B"].es, r.rows["B"].ef) == (date(2027, 3, 5), date(2027, 3, 8))


def test_empty_schedule_raises():
    with pytest.raises(ScheduleError) as e: compute(sched([], []))
    assert e.value.code == "empty"


@pytest.mark.parametrize("a", [
    Activity("M", "M", "finish_ms", "1", 2),
    Activity("M", "M", "start_ms", "1", 1),
    Activity("T", "T", "task", "1", 0),
    Activity("T", "T", "task", "1", 3, rd=-1),
])
def test_bad_duration_by_kind_raises(a):
    with pytest.raises(ScheduleError) as e: compute(sched([a], []))
    assert e.value.code == "bad_duration"


def test_self_relation_is_a_cycle():
    with pytest.raises(ScheduleError) as e: compute(sched([act("A", 1)], [Relation("A", "A")]))
    assert e.value.code == "cycle"


def test_late_dates_and_floats_on_parallel_branch():
    r = compute(sched([act("A", 5), act("B", 2), act("C", 1)], [Relation("A", "C"), Relation("B", "C")]))
    b, a, c = r.rows["B"], r.rows["A"], r.rows["C"]
    assert (b.ls, b.lf, b.tf, b.ff) == (date(2027, 3, 4), date(2027, 3, 5), 3, 3)
    assert (a.ls, a.lf, a.tf, a.ff) == (date(2027, 3, 1), date(2027, 3, 5), 0, 0)
    assert (c.ls, c.lf, c.tf, c.ff) == (date(2027, 3, 8), date(2027, 3, 8), 0, 0)
    assert r.finish == date(2027, 3, 8) and r.critical_path == ("A", "C")


def test_free_float_is_smaller_than_total_float_in_a_chain():
    # B(2) → D(1) 가지가 A(5) → C(1) 옆에 있고, D 뒤에는 아무것도 없다.
    r = compute(sched([act("A", 5), act("B", 2), act("C", 1), act("D", 1)],
                      [Relation("A", "C"), Relation("B", "D")]))
    assert (r.rows["B"].tf, r.rows["B"].ff) == (3, 0)
    assert (r.rows["D"].tf, r.rows["D"].ff) == (3, 3)


def test_critical_path_is_topological_with_id_ties():
    r = compute(sched([act("C", 1), act("B", 2), act("A", 2)], [Relation("B", "C"), Relation("A", "C")]))
    assert r.critical_path == ("A", "B", "C")


def test_fnlt_negative_float_is_critical_and_reaches_predecessor():
    b = act("B", 5, constraint=Constraint("FNLT", date(2027, 3, 5)))
    r = compute(sched([act("A", 5), b], [Relation("A", "B")]))
    assert r.rows["B"].tf == -5 and r.rows["A"].tf == -5
    assert r.critical_path == ("A", "B")


def test_snet_delays_start():
    a = act("A", 2, constraint=Constraint("SNET", date(2027, 3, 6)))
    r = compute(sched([a], []))
    assert (r.rows["A"].es, r.rows["A"].ef) == (date(2027, 3, 8), date(2027, 3, 9))


def test_start_milestone_does_not_cost_a_day():
    r = compute(sched([ms("S", "start_ms"), act("A", 2), ms("F", "finish_ms")],
                      [Relation("S", "A"), Relation("A", "F")]))
    assert r.rows["S"].es == r.rows["S"].ef == date(2027, 3, 1)
    assert (r.rows["A"].es, r.rows["A"].ef) == (date(2027, 3, 1), date(2027, 3, 2))
    assert r.rows["F"].es == date(2027, 3, 2)
    assert [r.rows[i].tf for i in "SAF"] == [0, 0, 0]
    assert r.critical_path == ("S", "A", "F")


def test_task_after_finish_milestone_starts_next_workday():
    r = compute(sched([act("A", 5), ms("F", "finish_ms"), act("B", 1)], [Relation("A", "F"), Relation("F", "B")]))
    assert r.rows["F"].es == date(2027, 3, 5) and r.rows["B"].es == date(2027, 3, 8)


def test_six_day_week_uses_saturday():
    r = compute(sched([act("A", 6), act("B", 1)], [Relation("A", "B")], CalendarSpec(6)))
    assert r.rows["A"].ef == date(2027, 3, 6) and r.rows["B"].es == date(2027, 3, 8)


def test_tagged_successor_waits_for_blocked_period():
    cal = CalendarSpec(7, blocked=(BlockedPeriod((3, 3), (3, 7), "타설"),))
    r = compute(sched([act("A", 2), act("B", 2, tags=("타설",))], [Relation("A", "B")], cal))
    assert (r.rows["B"].es, r.rows["B"].ef) == (date(2027, 3, 8), date(2027, 3, 9))
    assert r.rows["A"].ff == 5 and r.rows["A"].tf == 5


def test_actual_start_only_uses_remaining_duration():
    a = act("A", 5, rd=2, actual_start=date(2027, 3, 2), progress=0.6)
    r = compute(sched([a, act("B", 1)], [Relation("A", "B")]))
    assert (r.rows["A"].es, r.rows["A"].ef) == (date(2027, 3, 2), date(2027, 3, 3))
    assert r.rows["B"].es == date(2027, 3, 4)


def test_actual_start_only_without_rd_uses_od():
    a = act("A", 3, actual_start=date(2027, 3, 2))
    assert compute(sched([a], [])).rows["A"].ef == date(2027, 3, 4)


def test_actual_dates_are_not_moved_by_predecessor():
    b = act("B", 2, actual_start=date(2027, 3, 2), actual_finish=date(2027, 3, 3), progress=1.0)
    r = compute(sched([act("A", 5), b], [Relation("A", "B")]))
    assert (r.rows["B"].es, r.rows["B"].ef) == (date(2027, 3, 2), date(2027, 3, 3))


def test_actual_finish_without_actual_start_keeps_computed_start():
    b = act("B", 2, actual_finish=date(2027, 3, 12), progress=1.0)
    r = compute(sched([act("A", 3), b], [Relation("A", "B")]))
    assert (r.rows["B"].es, r.rows["B"].ef) == (date(2027, 3, 4), date(2027, 3, 12))


def test_completed_activity_late_dates_equal_early_but_float_is_computed():
    a = act("A", 2, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 2), progress=1.0)
    r = compute(sched([a, act("B", 1), act("C", 5)], [Relation("A", "B")]))
    row = r.rows["A"]
    assert (row.ls, row.lf) == (row.es, row.ef) == (date(2027, 3, 1), date(2027, 3, 2))
    assert row.tf == 2 and not row.critical       # B 는 3/3, 사업 종료는 3/5
    assert row.ff == 0


def test_free_float_never_exceeds_project_finish():
    # A 의 후행은 SS 뿐이라 A 의 종료를 묶는 것은 사업 종료일(3/5)이다.
    r = compute(sched([act("A", 3), act("B", 5), act("C", 1)], [Relation("A", "C", "SS", 0)]))
    assert r.finish == date(2027, 3, 5)
    assert (r.rows["A"].tf, r.rows["A"].ff) == (2, 0)
    r = compute(sched([act("A", 3), act("B", 5), act("C", 1)], [Relation("A", "C", "SS", -4)]))
    assert (r.rows["A"].tf, r.rows["A"].ff) == (2, 2)
