"""조건 점검(check). 작업 지시서의 시험과 controller 판단(R1·R2·R7)의 시험."""

from datetime import date

import pytest

from app.core.model import BlockedPeriod, CalendarSpec, Constraint, Relation, Resource
from app.harness.checks import CheckReport, Violation, check
from app.harness.conditions import BASE_RULES, Condition
from app.store.messages import SCHEDULE_ERROR_MESSAGES
from tests.schedules import make, task

BASE_IDS = [b.id for b in BASE_RULES]


def cond(cid: str, kind: str, params: dict, **k) -> Condition:
    return Condition(cid, "input", kind, params, "", "프롬프트", **k)


# ── 작업 지시서의 시험 ──────────────────────────────────────────────


def test_finish_by_violation_reports_days_over(s_finish_0305):
    r = check(s_finish_0305, [Condition("c1", "input", "finish_by", {"date": "2027-03-04"}, "준공 03.04 이전", "프롬프트")])
    assert r.violations[0].condition_id == "c1" and r.violations[0].amount == 1


# controller 판단 R1 로 바뀐 시험: 용량 1 의 겹침은 자원 맞춤이 일을 미뤄 풀므로 위반이 아니라
# 알림(notices)이다. 원래 기대는 r.violations[0].activity_ids == {"A", "B"} 였다.
def test_resource_cap_violation_lists_activities(two_crane_tasks):
    r = check(two_crane_tasks, [Condition("c2", "input", "resource_cap", {"resource_id": "crane", "capacity": 1}, "크레인 1대", "프롬프트")])
    assert r.violations == [] and set(r.notices[0].activity_ids) == {"A", "B"}


# controller 판단(fix round 1, F2)으로 바뀐 시험: 간격은 선행 종료와 후행 시작 "사이" 의 날 수다.
# 다음 근무일에 이어지면 간격 0 → 7 모자란다. 원래 기대는 amount == 6 이었다.
def test_min_gap_curing(pour_then_next_day):
    r = check(pour_then_next_day, [Condition("c3", "domain", "min_gap", {"after_tag": "타설", "days": 7}, "양생 7일", "분야 규칙")])
    assert r.violations and r.violations[0].amount == 7


def test_text_only_is_never_passed(s_finish_0305):
    r = check(s_finish_0305, [Condition("c4", "input", "text_only", {}, "안전 우선", "프롬프트")])
    assert r.uncheckable == ["c4"] and "c4" not in r.passed


def test_cycle_is_reported_not_raised(cyclic):
    assert check(cyclic, BASE_RULES).violations[0].condition_id == "base.no_cycle"


# ── 보고서 모양 ─────────────────────────────────────────────────────


def test_passed_lists_every_condition_without_a_violation(s_finish_0305):
    r = check(s_finish_0305, [*BASE_RULES, cond("c1", "finish_by", {"date": "2027-03-05"})])
    assert r == CheckReport(passed=[*BASE_IDS, "c1"], violations=[], uncheckable=[], notices=[], skipped=[])


def test_disabled_conditions_are_ignored(s_finish_0305):
    r = check(s_finish_0305, [cond("c1", "finish_by", {"date": "2027-03-04"}, enabled=False)])
    assert r == CheckReport(passed=[], violations=[], uncheckable=[], notices=[], skipped=[])


def test_duration_per_unit_is_not_checked(s_finish_0305):
    r = check(s_finish_0305, [cond("c5", "duration_per_unit", {}), cond("c4", "text_only", {})])
    assert r.uncheckable == ["c5", "c4"] and r.passed == [] and r.violations == []


# ── R1: 화면 날짜(맞춘 뒤)로 점검, 자원은 알림과 위반을 나눈다 ──────


def test_overlap_resolved_by_leveling_is_a_notice_and_the_condition_passes(two_crane_tasks):
    r = check(two_crane_tasks, [cond("c2", "resource_cap", {"resource_id": "crane", "capacity": 1})])
    assert r.passed == ["c2"] and r.violations == []
    assert r.notices == [
        Violation(
            "c2",
            "맞추기 전 날짜로는 타워크레인 필요량이 용량(1대)을 넘는 날이 3일 있습니다(최대 1대 초과).",
            ("A", "B"),
            1,
        )
    ]


def test_capacity_zero_leaves_an_overload_that_is_a_violation(two_crane_tasks):
    r = check(two_crane_tasks, [cond("c2", "resource_cap", {"resource_id": "crane", "capacity": 0})])
    assert r.passed == []
    assert r.violations == [
        Violation(
            "c2",
            "맞춘 뒤에도 타워크레인 필요량이 용량(0대)을 넘는 날이 3일 있습니다(최대 2대 초과).",
            ("A", "B"),
            2,
        )
    ]
    assert [(n.condition_id, n.activity_ids, n.amount) for n in r.notices] == [("c2", ("A", "B"), 2)]


def test_capacity_raised_by_the_condition_removes_the_overlap(two_crane_tasks):
    r = check(two_crane_tasks, [cond("c2", "resource_cap", {"resource_id": "crane", "capacity": 2})])
    assert (r.passed, r.violations, r.notices) == (["c2"], [], [])


def test_resource_cap_on_an_unknown_resource_is_a_violation(two_crane_tasks):
    r = check(two_crane_tasks, [cond("c2", "resource_cap", {"resource_id": "pump", "capacity": 1})])
    assert r.violations == [Violation("c2", "없는 자원을 가리킵니다.", (), None)] and r.notices == []


def test_finish_by_uses_the_leveled_finish(two_crane_tasks):
    # 맞추기 전 준공은 03.03 이지만 화면(맞춘 뒤) 준공은 03.08(월).
    r = check(two_crane_tasks, [cond("c1", "finish_by", {"date": "2027-03-05"})])
    assert r.violations == [Violation("c1", "준공이 기한보다 1일 늦습니다.", ("B",), 1)]


def test_min_gap_uses_the_leveled_dates():
    # X 가 크레인을 먼저 차지해 N 은 03.03 → 03.08 로 밀린다. 타설 P 의 종료(03.02)와 N 시작 사이
    # 근무일 3일(03.03·03.04·03.05). (fix round 1 F2 로 4·5 → 3·4)
    crane = Resource("crane", "타워크레인", "대", 1)
    s = make(
        [task("P", 2, tags=("타설",)), task("N", 1, resources=("crane",)), task("X", 5, resources=("crane",))],
        [Relation("P", "N")],
        [crane],
    )
    assert check(s, [cond("c3", "min_gap", {"after_tag": "타설", "days": 3})]).violations == []
    assert check(s, [cond("c3", "min_gap", {"after_tag": "타설", "days": 4})]).violations[0].amount == 1


def test_conditions_are_applied_before_checking(s_finish_0305):
    # 주 6일·공휴일: 03.01 삼일절이라 A 03.02~03.04, B 03.05~03.06(토). 준공 03.06.
    calendar = cond("c0", "calendar", {"days_per_week": 6, "holidays": "KR"})
    r = check(s_finish_0305, [calendar, cond("c1", "finish_by", {"date": "2027-03-05"})])
    assert r.passed == ["c0"] and r.violations == [Violation("c1", "준공이 기한보다 1일 늦습니다.", ("B",), 1)]


# ── R2: 계산이 안 되는 일정 ─────────────────────────────────────────

WINTER = CalendarSpec(5, (), (BlockedPeriod((1, 1), (12, 31), "겨울"),))
BROKEN = {
    "cycle": (make([task("A", 1), task("B", 1)], [Relation("A", "B"), Relation("B", "A")]), "base.no_cycle", ("A", "B")),
    "dangling_ref": (make([task("A", 1)], [Relation("A", "X")]), "base.no_dangling", ("A",)),
    "bad_duration": (make([task("A", 0)]), "base.valid", ("A",)),
    "empty": (make([]), "base.valid", ()),
    "duplicate_id": (make([task("A", 1), task("A", 2)]), "base.valid", ("A",)),
    "no_workdays": (make([task("A", 1, tags=("겨울",))], cal=WINTER), "base.calendar", ()),
}


@pytest.mark.parametrize("code", list(BROKEN))
def test_schedule_error_is_reported_under_its_base_rule(code):
    schedule, rule, ids = BROKEN[code]
    conditions = [*BASE_RULES, cond("c1", "finish_by", {"date": "2027-03-04"}), cond("c4", "text_only", {})]
    r = check(schedule, conditions)
    assert r.violations == [Violation(rule, SCHEDULE_ERROR_MESSAGES[code], ids, None)]
    assert r.skipped == [i for i in BASE_IDS if i != rule] + ["c1"]
    assert (r.passed, r.notices, r.uncheckable) == ([], [], ["c4"])


def test_schedule_error_is_reported_even_without_base_rules(cyclic):
    r = check(cyclic, [cond("c1", "finish_by", {"date": "2027-03-04"})])
    assert [v.condition_id for v in r.violations] == ["base.no_cycle"] and r.skipped == ["c1"]


# ── R7: 잣대마다의 양(근무일) ───────────────────────────────────────


def test_milestone_by(s_finish_0305):
    late = check(s_finish_0305, [cond("m", "milestone_by", {"activity_id": "A", "date": "2027-03-02"})])
    assert late.violations == [Violation("m", "A 종료가 기한보다 1일 늦습니다.", ("A",), 1)]
    on_time = check(s_finish_0305, [cond("m", "milestone_by", {"activity_id": "A", "date": "2027-03-03"})])
    assert on_time.passed == ["m"]
    missing = check(s_finish_0305, [cond("m", "milestone_by", {"activity_id": "Z", "date": "2027-03-03"})])
    assert missing.violations == [Violation("m", "없는 액티비티를 가리킵니다.", (), None)]


def test_start_after_flags_work_that_starts_before_the_date():
    # A 는 03.01 에 이미 시작했다(실적). 시작 가능일 03.03 → 2 근무일 이르다.
    s = make([task("A", 3, actual_start=date(2027, 3, 1)), task("B", 2)], [Relation("A", "B")])
    r = check(s, [cond("s", "start_after", {"date": "2027-03-03"})])
    assert r.violations == [
        Violation("s", "시작 가능일보다 먼저 시작하는 액티비티가 1개 있습니다(최대 2일 이름).", ("A",), 2)
    ]


def test_start_after_counts_to_the_next_workday():
    s = make([task("A", 1, actual_start=date(2027, 3, 5))])  # 금요일 실적, 시작 가능일은 토요일
    assert check(s, [cond("s", "start_after", {"date": "2027-03-06"})]).violations[0].amount == 1


def test_start_after_passes_once_applied(s_finish_0305):
    assert check(s_finish_0305, [cond("s", "start_after", {"date": "2027-03-03"})]).passed == ["s"]


def test_max_duration(s_finish_0305):
    r = check(s_finish_0305, [cond("x", "max_duration", {"days": 1})])
    assert r.violations == [Violation("x", "기간이 1일을 넘는 액티비티가 2개 있습니다(최대 2일 초과).", ("A", "B"), 2)]
    assert check(s_finish_0305, [cond("x", "max_duration", {"days": 3})]).passed == ["x"]


def test_min_gap_takes_the_worst_relation_and_ignores_untagged_predecessors():
    # P(타설)→N 은 다음 근무일(간격 0), Q(타설)→R 은 FS lag 5(간격 5), N→T 는 타설이 아니다.
    # (fix round 1 F2 로 간격 1·6, 최대 6일 부족 → 간격 0·5, 최대 7일 부족)
    s = make(
        [task("P", 2, tags=("타설",)), task("N", 1), task("Q", 2, tags=("타설",)), task("R", 1), task("T", 1)],
        [Relation("P", "N"), Relation("Q", "R", lag=5), Relation("N", "T")],
    )
    r = check(s, [cond("g", "min_gap", {"after_tag": "타설", "days": 7})])
    assert r.violations == [
        Violation("g", "'타설' 뒤 간격이 근무일 7일보다 짧은 곳이 2곳 있습니다(최대 7일 부족).", ("N", "P", "Q", "R"), 7)
    ]


def test_min_gap_counts_the_days_strictly_between():
    # fix round 1 F2: FS lag 6 이면 사이 근무일 6일 → 7일 양생에 1 모자란다. lag 7 이면 통과.
    lag6 = make([task("P", 2, tags=("타설",)), task("N", 1)], [Relation("P", "N", lag=6)])
    lag7 = make([task("P", 2, tags=("타설",)), task("N", 1)], [Relation("P", "N", lag=7)])
    curing = cond("g", "min_gap", {"after_tag": "타설", "days": 7})
    assert check(lag6, [curing]).violations[0].amount == 1
    assert check(lag7, [curing]).passed == ["g"]


def test_min_gap_in_calendar_days_counts_the_weekend():
    # P(타설) 03.01~03.05(금), N 03.08(월): 사이 달력일 2일(토·일), 근무일 0일.
    s = make([task("P", 5, tags=("타설",)), task("N", 1)], [Relation("P", "N")])
    calendar_days = {"after_tag": "타설", "unit": "calendar_days"}
    assert check(s, [cond("g", "min_gap", {**calendar_days, "days": 2})]).passed == ["g"]
    r = check(s, [cond("g", "min_gap", {**calendar_days, "days": 3})])
    assert r.violations == [
        Violation("g", "'타설' 뒤 간격이 달력일 3일보다 짧은 곳이 1곳 있습니다(최대 1일 부족).", ("N", "P"), 1)
    ]
    assert check(s, [cond("g", "min_gap", {"after_tag": "타설", "days": 1})]).violations[0].amount == 1


WINTER_POUR = {"start_md": [12, 1], "end_md": [2, 28], "tag": "타설"}


def test_blocked_period_guard_flags_actual_work_inside_the_period():
    s = make([task("W", 3, tags=("타설",), actual_start=date(2027, 12, 6), actual_finish=date(2027, 12, 8)), task("V", 1)])
    r = check(s, [cond("b", "blocked_period", WINTER_POUR)])
    assert r.violations == [Violation("b", "'타설' 금지 기간에 일하는 액티비티가 1개 있습니다.", ("W",), None)]


def test_blocked_period_passes_for_work_that_pauses_over_the_period():
    # 11.29(월) 시작 5일: 11.29·11.30 일하고 쉬었다가 2028.02.29 부터 다시 → 금지 기간 안에서 일하지 않는다.
    s = make([task("P", 5, tags=("타설",), constraint=Constraint("SNET", date(2027, 11, 29)))])
    assert check(s, [cond("b", "blocked_period", WINTER_POUR)]).passed == ["b"]


def test_calendar_guard_flags_a_calendar_condition_that_is_not_in_force(s_finish_0305):
    # 두 달력 조건을 그대로 넘기면 뒤 것이 달력이 된다. 앞 것은 지켜지지 않은 것으로 나온다.
    six = cond("c6", "calendar", {"days_per_week": 6, "holidays": "KR"})
    five = cond("c5", "calendar", {"days_per_week": 5, "holidays": []})
    r = check(s_finish_0305, [*BASE_RULES, six, five])
    assert r.violations == [Violation("c6", "달력이 조건(주 6일 근무)과 다릅니다.", (), None)]
    assert r.passed == [*BASE_IDS, "c5"]


# ── fix round 1: 형식이 틀린 조건은 invalid 로 (F1, M6) ─────────────

MALFORMED = {
    "bad_cap": ("resource_cap", {"resource_id": "crane", "capacity": "2"}, "'capacity' 칸 값이 올바르지 않습니다: 0 이상의 정수"),
    "bad_holidays": ("calendar", {"days_per_week": 6, "holidays": "kr"},
                     "'holidays' 칸 값이 올바르지 않습니다: \"KR\" 또는 날짜(YYYY-MM-DD) 목록"),
    "bad_finish": ("finish_by", {}, "'date' 칸이 없습니다."),
    "bad_gap": ("min_gap", {"after_tag": "타설", "days": "7"}, "'days' 칸 값이 올바르지 않습니다: 0 이상의 정수"),
}


@pytest.mark.parametrize("cid", list(MALFORMED))
def test_malformed_condition_is_listed_as_invalid_and_the_rest_is_checked(two_crane_tasks, cid):
    kind, params, message = MALFORMED[cid]
    r = check(two_crane_tasks, [*BASE_RULES, cond(cid, kind, params), cond("c1", "finish_by", {"date": "2027-03-05"})])
    assert r.invalid == [{"condition_id": cid, "message": message}]
    assert r.passed == BASE_IDS and [v.condition_id for v in r.violations] == ["c1"]
    assert cid not in r.uncheckable + r.skipped and r.notices == []


def test_invalid_conditions_are_not_skipped_when_the_schedule_is_broken(cyclic):
    r = check(cyclic, [*BASE_RULES, cond("bad", "finish_by", {"date": "3월 4일"}), cond("c1", "max_duration", {"days": 3})])
    assert r.invalid == [{"condition_id": "bad", "message": "'date' 칸 값이 올바르지 않습니다: 날짜(YYYY-MM-DD)"}]
    assert r.skipped == [*BASE_IDS[1:], "c1"]


def test_a_non_base_id_in_the_base_layer_is_invalid(s_finish_0305):
    r = check(s_finish_0305, [Condition("x", "base", "no_cycle", {}, "", "기본 규칙")])
    assert r.invalid == [{"condition_id": "x", "message": "기본 규칙은 바꿀 수 없습니다."}] and r.passed == []


def test_base_rules_are_recognised_by_id(s_finish_0305):
    moved = Condition("base.no_cycle", "input", "no_cycle", {}, "", "프롬프트")
    assert check(s_finish_0305, [moved]).passed == ["base.no_cycle"]


# ── fix round 1: 자원 조건은 자기 용량으로 잰다 (M5) ─────────────────


def test_resource_cap_is_judged_by_its_own_capacity(two_crane_tasks):
    # 조립하지 않은 목록: 일정에는 이긴 조건(2대)이 들어가 둘이 같이 일한다. 진 조건(1대)은 지켜지지 않는다.
    one = Condition("d1", "domain", "resource_cap", {"resource_id": "crane", "capacity": 1}, "", "분야 규칙")
    two = cond("i1", "resource_cap", {"resource_id": "crane", "capacity": 2})
    r = check(two_crane_tasks, [one, two])
    assert r.passed == ["i1"]
    assert r.violations == [
        Violation(
            "d1",
            "맞춘 뒤에도 타워크레인 필요량이 용량(1대)을 넘는 날이 3일 있습니다(최대 1대 초과).",
            ("A", "B"),
            1,
        )
    ]


# ── fix round 1: 날짜가 늦으면 양은 1 이상 (M8) ─────────────────────


def test_a_saturday_finish_after_a_friday_deadline_is_one_day_late():
    s = make([task("A", 1, actual_start=date(2027, 3, 5), actual_finish=date(2027, 3, 6))])
    r = check(s, [cond("f", "finish_by", {"date": "2027-03-05"}), cond("m", "milestone_by", {"activity_id": "A", "date": "2027-03-05"})])
    assert [(v.condition_id, v.message, v.amount) for v in r.violations] == [
        ("f", "준공이 기한보다 1일 늦습니다.", 1),
        ("m", "A 종료가 기한보다 1일 늦습니다.", 1),
    ]



# ── fix round 2 ─────────────────────────────────────────────────────


def test_dates_out_of_range_and_huge_month_days_are_invalid_not_raised(s_finish_0305):
    conditions = [
        *BASE_RULES,
        cond("far", "start_after", {"date": "9999-12-31"}),
        cond("old", "finish_by", {"date": "0001-01-01"}),
        cond("huge", "blocked_period", {"start_md": [2147483648, 1], "end_md": [3, 1], "tag": "타설"}),
    ]
    r = check(s_finish_0305, conditions)
    assert [i["condition_id"] for i in r.invalid] == ["far", "old", "huge"]
    assert r.passed == BASE_IDS and r.violations == []


def test_a_base_rule_kind_under_another_id_is_invalid(s_finish_0305):
    r = check(s_finish_0305, [cond("x", "no_dangling", {})])
    assert r.invalid == [{"condition_id": "x", "message": "기본 규칙 종류는 바꿀 수 없습니다."}] and r.passed == []


def test_earlier_conditions_with_a_repeated_id_are_invalid_and_the_last_is_used(s_finish_0305):
    r = check(s_finish_0305, [cond("c1", "finish_by", {"date": "2027-03-04"}), cond("c1", "max_duration", {"days": 1})])
    assert r.invalid == [{"condition_id": "c1", "message": "같은 id 의 조건이 뒤에 다시 있습니다."}]
    assert [(v.condition_id, v.amount) for v in r.violations] == [("c1", 2)]  # max_duration: A 3일 − 1
