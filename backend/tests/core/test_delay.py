from dataclasses import replace
from datetime import date

import pytest

from app.core.cpm import ScheduleError
from app.core.delay import (
    FINISHED_NOTE,
    MILESTONE_NOTE,
    Clash,
    DelayEvent,
    DelayInputError,
    MilestoneShift,
    analyze,
    diff_impact,
    insert_delay,
    ordered,
)
from app.core.model import (
    Activity,
    BlockedPeriod,
    CalendarSpec,
    Constraint,
    Relation,
    Resource,
)
from tests.core.helpers import act, sched

# CAL5 = 주 5일·공휴일 없음, 2027-03-01 월
BASE = sched([act("A", 3), act("B", 2), act("C", 1)], [Relation("A", "B"), Relation("A", "C")])   # A 3/1~3/3, B 3/4~3/5, C 3/4, 준공 3/5
FNLT_B = sched([act("A", 3), replace(act("B", 2), constraint=Constraint("FNLT", date(2027, 3, 12)))], [Relation("A", "B")])


def ev(i, aid, day, days, cost=None): return DelayEvent(i, aid, date(2027, 3, day), days, cost)


def test_critical_delay_moves_finish():
    i = analyze(BASE, [ev("e1", "B", 4, 2)]).impacts[0]
    assert (i.finish_before, i.finish_after, i.finish_delta, i.absorbed) == (date(2027, 3, 5), date(2027, 3, 9), 2, 0)
    assert i.affected == ("B",) and i.critical_added == () and i.cost is None
def test_float_absorbs_noncritical_delay():
    i = analyze(BASE, [ev("e1", "C", 4, 1)]).impacts[0]
    assert (i.finish_delta, i.absorbed, i.critical_added) == (0, 1, ("C",))
def test_events_are_inserted_in_start_order_each_with_its_share():
    r = analyze(BASE, [ev("b", "B", 3, 2), ev("c", "C", 2, 1)])
    assert [x.event_id for x in r.impacts] == ["c", "b"] and [x.finish_delta for x in r.impacts] == [0, 2]
    assert (r.final_finish, r.total_delta, r.total_absorbed) == (date(2027, 3, 9), 2, 1)
def test_not_started_task_starts_later_with_the_same_duration():       # PM 결정 11-20
    s = analyze(BASE, [ev("e1", "B", 4, 2)])
    after = insert_delay(BASE, ev("e1", "B", 4, 2))[0]
    b = next(a for a in after.activities if a.id == "B")
    assert b.od == 2 and b.constraint == Constraint("SNET", date(2027, 3, 8))   # 맞춘 ES 3/4 → 2 근무일 뒤 3/8
    assert s.impacts[0].finish_after == date(2027, 3, 9)
def test_not_started_task_with_fnlt_keeps_it_and_hides_the_helper_milestone():
    s = sched([act("A", 3), replace(act("B", 2), constraint=Constraint("FNLT", date(2027, 3, 12)))], [Relation("A", "B")])
    i = analyze(s, [ev("e", "B", 4, 2)]).impacts[0]
    assert i.finish_after == date(2027, 3, 9) and all(not x.startswith("~") for x in i.affected + i.critical_added)
def test_in_progress_adds_to_remaining():
    s = replace(sched([act("A", 3, actual_start=date(2027, 3, 1), rd=1), act("B", 2), act("C", 1)], [Relation("A", "B"), Relation("A", "C")]), data_date=date(2027, 3, 2))
    i = analyze(s, [ev("e", "A", 2, 2)]).impacts[0]                      # 준공 3/4 → 3/8
    assert (i.finish_before, i.finish_after, i.finish_delta) == (date(2027, 3, 4), date(2027, 3, 8), 2)
def test_finished_activity_is_not_inserted():
    s = sched([act("A", 3, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 3), progress=1.0), act("B", 2)], [Relation("A", "B")])
    i = analyze(s, [ev("e", "A", 2, 2)]).impacts[0]
    assert (i.applied, i.note, i.finish_delta, i.absorbed) == (False, FINISHED_NOTE, 0, 0)
def test_cost_is_finish_delta_times_daily_cost():
    assert analyze(BASE, [ev("e", "B", 4, 2, 3_100_000)]).impacts[0].cost == 6_200_000
    assert analyze(BASE, [ev("e", "C", 4, 1, 3_100_000)]).impacts[0].cost == 0
def test_milestone_shift_is_reported():
    s = sched([act("A", 3), act("B", 2), Activity("M", "준공", "finish_ms", "1", 0)], [Relation("A", "B"), Relation("B", "M")])
    assert analyze(s, [ev("e", "B", 4, 2)]).impacts[0].milestones == (MilestoneShift("M", date(2027, 3, 5), date(2027, 3, 9), 2),)
def test_new_resource_clash_and_leveling():
    R = Resource("crane", "타워크레인", "대", 1)
    s = replace(sched([act("A", 2, resources=("crane",)), act("X", 3), act("D", 2, resources=("crane",))], [Relation("X", "D")]), resources=(R,))
    i = analyze(s, [ev("e", "A", 1, 2)]).impacts[0]                      # A 가 3/3~3/4 로 밀려 D(3/4~) 와 겹침 → 맞춤이 D 를 3/5~3/8 로
    assert i.new_clashes == (Clash("crane", date(2027, 3, 4), 1, 1),) and (i.finish_delta, i.absorbed) == (1, 1)
def test_bad_input_raises():
    with pytest.raises(DelayInputError) as e:
        analyze(BASE, [ev("e", "Z", 4, 1)])
    assert e.value.message == "없는 액티비티입니다: Z"
    with pytest.raises(DelayInputError):
        analyze(BASE, [ev("e", "B", 4, 0)])
def test_diff_impact_between_two_schedules():                             # 실적에서 감지한 지연(이미 일정에 들어감)용
    after = sched([act("A", 3), act("B", 4), act("C", 1)], [Relation("A", "B"), Relation("A", "C")])
    assert diff_impact(BASE, after, event_id="x", days=2, daily_cost=None).finish_delta == 2


# 아래는 brief 밖에서 더한 시험


def test_ordered_sorts_by_start_then_id():
    events = [ev("b", "B", 3, 1), ev("a", "C", 3, 1), ev("c", "A", 2, 1)]
    assert [e.id for e in ordered(events)] == ["c", "a", "b"]


def test_zero_days_message_and_event_id():
    with pytest.raises(DelayInputError) as e:
        insert_delay(BASE, ev("e7", "B", 4, 0))
    assert (e.value.event_id, e.value.message) == ("e7", "지연 일수는 1일 이상이어야 합니다.")


def test_pushed_start_leaves_float_to_its_predecessor():
    # B 의 시작을 SNET 으로 미루면 A 는 B 를 기다리지 않아도 되므로 여유 2일이 생긴다
    i = analyze(BASE, [ev("e1", "B", 4, 2)]).impacts[0]
    assert i.critical_removed == ("A",)


def test_existing_snet_is_raised_to_the_new_bound():
    s = sched([act("A", 3), replace(act("B", 2), constraint=Constraint("SNET", date(2027, 3, 10)))], [Relation("A", "B")])
    b = next(a for a in insert_delay(s, ev("e", "B", 10, 2))[0].activities if a.id == "B")
    assert b.constraint == Constraint("SNET", date(2027, 3, 12))   # 맞춘 ES 3/10 → 2 근무일 뒤 3/12


def test_in_progress_without_rd_adds_to_original_duration():
    s = sched([act("A", 3, actual_start=date(2027, 3, 1)), act("B", 2)], [Relation("A", "B")])
    a = next(x for x in insert_delay(s, ev("e", "A", 2, 2))[0].activities if x.id == "A")
    assert (a.od, a.rd) == (3, 5)
    i = analyze(s, [ev("e", "A", 2, 2)]).impacts[0]                      # 준공 3/5 → 3/9
    assert (i.finish_before, i.finish_after, i.finish_delta) == (date(2027, 3, 5), date(2027, 3, 9), 2)


def test_fnlt_helper_milestone_is_built_once_and_moved_by_a_second_delay():
    once = insert_delay(FNLT_B, ev("e1", "B", 4, 2))[0]
    twice = insert_delay(once, ev("e2", "B", 8, 1))[0]
    b = next(a for a in twice.activities if a.id == "B")
    helpers = [a for a in twice.activities if a.id == "~B"]
    assert b.constraint == Constraint("FNLT", date(2027, 3, 12)) and b.od == 2
    assert len(helpers) == 1 and helpers[0].kind == "start_ms"
    assert helpers[0].constraint == Constraint("SNET", date(2027, 3, 9))   # 그때 맞춘 ES 3/8 → 1 근무일 뒤 3/9
    assert twice.relations.count(Relation("~B", "B")) == 1
    r = analyze(FNLT_B, [ev("e1", "B", 4, 2), ev("e2", "B", 8, 1)])
    assert [x.finish_delta for x in r.impacts] == [2, 1] and r.final_finish == date(2027, 3, 10)


TILDE = "'~' 로 시작하는 액티비티 id 는 쓸 수 없습니다."


def test_event_on_a_tilde_id_is_rejected():
    with pytest.raises(DelayInputError) as e:
        analyze(FNLT_B, [ev("e1", "B", 4, 2), ev("e2", "~B", 8, 1)])
    assert (e.value.event_id, e.value.message) == ("e2", TILDE)
    with pytest.raises(DelayInputError) as e:
        insert_delay(BASE, ev("e3", "~A", 4, 1))
    assert (e.value.event_id, e.value.message) == ("e3", TILDE)


def test_schedule_with_a_tilde_id_is_rejected_not_hidden():
    s = sched([act("A", 3), act("~X", 1)], [Relation("A", "~X")])
    with pytest.raises(DelayInputError) as e:
        analyze(s, [ev("late", "A", 5, 1), ev("early", "A", 1, 1)])
    assert (e.value.event_id, e.value.message) == ("early", TILDE)   # 차례상 첫 사건


def test_milestone_event_is_not_inserted_and_costs_nothing():
    s = sched([act("A", 3), Activity("M", "준공", "finish_ms", "1", 0)], [Relation("A", "M")])
    assert insert_delay(s, ev("e", "M", 3, 2)) == (s, MILESTONE_NOTE)
    i = analyze(s, [ev("e", "M", 3, 2, 3_100_000)]).impacts[0]
    assert (i.applied, i.note, i.finish_delta, i.absorbed, i.cost, i.affected) == (False, MILESTONE_NOTE, 0, 0, 0, ())


def test_schedule_error_passes_through():
    s = sched([act("A", 1), act("B", 1)], [Relation("A", "B"), Relation("B", "A")])
    with pytest.raises(ScheduleError) as e:
        analyze(s, [ev("e", "A", 1, 1)])
    assert e.value.code == "cycle"


def test_no_events_keeps_the_base_finish():
    r = analyze(BASE, [])
    assert (r.base_finish, r.final_finish, r.total_delta, r.total_absorbed, r.impacts) == (date(2027, 3, 5), date(2027, 3, 5), 0, 0, ())


def test_clash_that_was_already_there_is_not_new():
    R = Resource("crane", "타워크레인", "대", 1)
    s = replace(sched([act("A", 2, resources=("crane",)), act("B", 2, resources=("crane",)), act("C", 1)], []), resources=(R,))
    assert analyze(s, [ev("e", "C", 1, 1)]).impacts[0].new_clashes == ()   # 3/1·3/2 겹침은 넣기 전에도 있었다


def test_start_is_pushed_by_the_activity_own_workdays():
    cal = CalendarSpec(5, blocked=(BlockedPeriod((3, 5), (3, 5), "타설"),))
    s = sched([act("A", 3), act("B", 2, tags=("타설",))], [Relation("A", "B")], cal=cal)
    b = next(a for a in insert_delay(s, ev("e", "B", 4, 2))[0].activities if a.id == "B")
    assert b.constraint == Constraint("SNET", date(2027, 3, 9))   # 맞춘 ES 3/4, 3/5 는 B 의 쉬는 날 → 3/8, 3/9


def test_delay_moves_a_leveled_task_from_its_leveled_start():         # 컨트롤러 판정 11-20
    R = Resource("crane", "타워크레인", "대", 1)
    s = replace(sched([act("A", 2, resources=("crane",)), act("B", 2, resources=("crane",))], []), resources=(R,))
    # 맞추기 전 A·B 모두 3/1, 맞춘 뒤 A 3/1~3/2, B 3/3~3/4 (2일 밀림)
    b = next(a for a in insert_delay(s, ev("e", "B", 3, 3))[0].activities if a.id == "B")
    assert b.constraint == Constraint("SNET", date(2027, 3, 8))   # 맞춘 시작 3/3 → 3 근무일 뒤 3/8 (맞추기 전 3/1 기준이면 3/4)
    i = analyze(s, [ev("e", "B", 3, 3)]).impacts[0]
    assert (i.finish_before, i.finish_after, i.finish_delta, i.absorbed) == (date(2027, 3, 4), date(2027, 3, 9), 3, 0)
