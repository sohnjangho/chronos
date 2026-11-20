"""승인 판단(decide·assess): 계산한 결과(조건을 넣은 화면 날짜)를 비교해 사람이 승인해야 하는지 정한다."""

from dataclasses import replace

import pytest

from app.agent.approval import Decision, assess, decide
from app.agent.context import system_prompt
from app.core.model import Activity, Relation, WbsNode
from app.harness.checks import CheckReport, Violation
from tests.approval_doubles import OK, crane, finish_by, net

C = [crane(1)]
C_CRANE_2 = [crane(2)]
BAD = CheckReport(passed=[], violations=[Violation("in.finish_by", "준공이 기한보다 1일 늦습니다.", ("D",), 1)],
                  uncheckable=[])


@pytest.fixture
def s():
    """A 3/1~3/3 → B 3/4~3/9 → D 3/10, A → C 3/4 → D. 준공 3/10, 크리티컬 A·B·D, C 여유 3일."""
    return net()


@pytest.fixture
def s_noncritical_plus2():
    return net(c=3)  # C 3/4~3/8, 여유 1일 — 준공·크리티컬 그대로


@pytest.fixture
def s_finish_plus4():
    return net(b=8)  # B 3/4~3/15, D 3/16 — 준공이 근무일 4일(달력 6일) 늦어짐


@pytest.fixture
def s_other_path():
    return net(b=2, c=4)  # 준공 3/10 그대로, 크리티컬이 A·B·D → A·C·D


@pytest.fixture
def s_minus_one(s):
    return replace(
        s,
        activities=tuple(a for a in s.activities if a.id != "C"),
        relations=tuple(r for r in s.relations if "C" not in (r.pred, r.succ)),
    )


# ── 지시서 시험 ─────────────────────────────────────────────────────


def test_absorbed_in_float_is_auto(s, s_noncritical_plus2):
    assert decide(s, s_noncritical_plus2, C, C, OK).needs_approval is False


def test_finish_change_needs_approval(s, s_finish_plus4):
    assert "finish_changed" in decide(s, s_finish_plus4, C, C, OK).reasons


def test_critical_path_change(s, s_other_path):
    assert "critical_path_changed" in decide(s, s_other_path, C, C, OK).reasons


def test_condition_change(s):
    assert "condition_changed" in decide(s, s, C, C_CRANE_2, OK).reasons


def test_first_save_always_needs_approval(s):
    assert decide(None, s, [], C, OK).reasons == ["first_save"]


def test_delete_activity_is_structure_change(s, s_minus_one):
    assert "structure_changed" in decide(s, s_minus_one, C, C, OK).reasons


def test_mode_all_and_auto(s, s_noncritical_plus2, s_finish_plus4):
    assert decide(s, s_noncritical_plus2, C, C, OK, mode="all").needs_approval
    assert not decide(s, s_finish_plus4, C, C, OK, mode="auto").needs_approval


# ── R3: 계산 결과로 비교 ────────────────────────────────────────────


def test_each_change_gives_exactly_its_reason(s, s_noncritical_plus2, s_finish_plus4, s_other_path, s_minus_one):
    assert decide(s, s_noncritical_plus2, C, C, OK) == Decision(False, [])
    assert decide(s, s_finish_plus4, C, C, OK) == Decision(True, ["finish_changed"])
    assert decide(s, s_other_path, C, C, OK) == Decision(True, ["critical_path_changed"])
    assert decide(s, s_minus_one, C, C, OK) == Decision(True, ["structure_changed"])
    assert decide(s, s, C, C_CRANE_2, OK) == Decision(True, ["condition_changed"])


def test_conditions_are_applied_before_comparing():
    """같은 일정이라도 조건(크레인 1대 → 2대)이 계산 날짜를 바꾸면 준공 변경이다(입력만 보면 같다)."""
    sc = net(crane_on=("B", "C"))  # B·C 가 같은 날 크레인을 쓴다 — 1대면 맞춤이 하나를 미룬다
    reasons = decide(sc, sc, C, C_CRANE_2, OK).reasons
    assert "finish_changed" in reasons and "condition_changed" in reasons


def test_additions_alone_are_not_a_structure_change(s):
    added = net(extra=(Activity("E", "작업 E", "task", "1", 1),), extra_rels=(Relation("A", "E"),))
    assert decide(s, added, C, C, OK) == Decision(False, [])  # E 는 여유가 있어 준공·크리티컬 그대로


def test_deleting_a_relation_is_a_structure_change(s):
    fewer = replace(s, relations=tuple(r for r in s.relations if (r.pred, r.succ) != ("C", "D")))
    assert decide(s, fewer, C, C, OK).reasons == ["structure_changed"]


def test_moving_an_activity_to_another_wbs_is_a_structure_change(s):
    more_wbs = replace(s, wbs=(*s.wbs, WbsNode("2", "마감", None)))
    assert decide(s, more_wbs, C, C, OK).reasons == []  # WBS 를 더하기만 한 것은 아니다
    moved = replace(more_wbs, activities=tuple(replace(a, wbs="2") if a.id == "C" else a for a in s.activities))
    assert decide(s, moved, C, C, OK).reasons == ["structure_changed"]


def test_a_milestone_on_a_float_path_that_moves_is_a_milestone_change():
    ms = (Activity("M", "C 끝", "finish_ms", "1", 0),)
    before, after = net(extra=ms, extra_rels=(Relation("C", "M"),)), net(c=3, extra=ms, extra_rels=(Relation("C", "M"),))
    assert decide(before, after, C, C, OK).reasons == ["milestone_changed"]


def test_violations_need_approval_in_every_mode(s, s_noncritical_plus2):
    for mode in ("all", "important", "auto"):
        d = decide(s, s_noncritical_plus2, C, C, BAD, mode=mode)
        assert d == Decision(True, ["condition_violated"])


def test_condition_text_alone_is_not_a_condition_change(s):
    reworded = [{**crane(1), "text": "크레인은 한 대만"}]
    assert decide(s, s, C, reworded, OK).reasons == []


def test_turning_a_condition_off_is_a_condition_change(s):
    assert decide(s, s, C, [{**crane(1), "enabled": False}], OK).reasons == ["condition_changed"]


def test_first_save_with_a_violation_and_auto_mode(s):
    assert decide(None, s, [], C, BAD).reasons == ["first_save", "condition_violated"]
    assert decide(None, s, [], C, OK, mode="auto").needs_approval is False
    assert decide(None, s, [], C, BAD, mode="auto").needs_approval is True
    assert decide(None, s, [], C, OK, mode="all").needs_approval is True


# ── R4: 화면에 보일 요약과 차이 ─────────────────────────────────────


def test_summary_of_a_finish_change(s, s_finish_plus4):
    due = [finish_by("2027-03-19")]
    result = assess(s, s_finish_plus4, due, due, OK)
    assert result.summary == {
        "finish": {"before": "2027-03-10", "after": "2027-03-16", "delta_days": 6},
        "critical": {"before_count": 3, "after_count": 3, "path_changed": False},
        "conditions_changed": [],
        "changed_count": 2,
        "check": {"passed": 0, "violations": [], "uncheckable": 0, "invalid": 0},
        "finish_float": {"before": 7, "after": 3},  # 준공 → 기한 3/19 사이 근무일
    }
    assert result.diff == [
        {"activity_id": "B", "name": "작업 B", "before": {"start": "2027-03-04", "finish": "2027-03-09"},
         "after": {"start": "2027-03-04", "finish": "2027-03-15"}, "finish_delta": 6},
        {"activity_id": "D", "name": "작업 D", "before": {"start": "2027-03-10", "finish": "2027-03-10"},
         "after": {"start": "2027-03-16", "finish": "2027-03-16"}, "finish_delta": 6},
    ]


def test_summary_of_an_earlier_finish_and_a_new_path(s_other_path):
    summary = assess(s_other_path, net(b=2, c=1), C, C, OK).summary  # C 4 → 1: 준공 3/10 → 3/8
    assert summary["finish"] == {"before": "2027-03-10", "after": "2027-03-08", "delta_days": -2}
    assert summary["critical"] == {"before_count": 3, "after_count": 3, "path_changed": True}
    assert summary["finish_float"] == {"before": None, "after": None}  # 기한 조건이 없다


def test_condition_changes_are_described_in_words(s):
    summary = assess(s, s, [crane(1), finish_by("2027-03-19")], [crane(2)], OK).summary
    assert summary["conditions_changed"] == [
        {"id": "in.finish_by", "name": "준공 2027-03-19까지", "before": "2027-03-19", "after": None},
        {"id": "in.resource_cap.crane", "name": "타워크레인", "before": "1대", "after": "2대"},
    ]


def test_check_counts_and_violation_lines():
    report = CheckReport(passed=["base.no_cycle", "in.resource_cap.crane"], uncheckable=["in.text_only"],
                         violations=BAD.violations, invalid=[{"condition_id": "x", "message": "틀림"}])
    check = assess(net(), net(), C, C, report).summary["check"]
    assert check == {
        "passed": 2,  # 점검한 것만 센다(점검 안 된 조건은 따로)
        "violations": [{"condition_id": "in.finish_by", "message": "준공이 기한보다 1일 늦습니다.",
                        "activity_ids": ["D"], "amount": 1}],
        "uncheckable": 1,
        "invalid": 1,
    }


def test_diff_lists_only_changed_activities_and_deleted_ones(s, s_minus_one, s_noncritical_plus2):
    assert assess(s, s_noncritical_plus2, C, C, OK).diff == [
        {"activity_id": "C", "name": "작업 C", "before": {"start": "2027-03-04", "finish": "2027-03-04"},
         "after": {"start": "2027-03-04", "finish": "2027-03-08"}, "finish_delta": 4},
    ]
    assert assess(s, s_minus_one, C, C, OK).diff == [
        {"activity_id": "C", "name": "작업 C", "before": {"start": "2027-03-04", "finish": "2027-03-04"},
         "after": None, "finish_delta": None},
        # D 는 날짜가 그대로지만 선행(C)이 빠져 입력이 바뀌었다
        {"activity_id": "D", "name": "작업 D", "before": {"start": "2027-03-10", "finish": "2027-03-10"},
         "after": {"start": "2027-03-10", "finish": "2027-03-10"}, "finish_delta": 0},
    ]


def test_first_save_summary_and_diff(s):
    result = assess(None, s, [], C, OK)
    assert result.summary["finish"] == {"before": None, "after": "2027-03-10", "delta_days": None}
    assert result.summary["critical"] == {"before_count": None, "after_count": 3, "path_changed": False}
    assert result.summary["conditions_changed"] == [] and result.summary["changed_count"] == 4
    assert [r["activity_id"] for r in result.diff] == ["A", "B", "C", "D"]
    assert all(r["before"] is None and r["finish_delta"] is None for r in result.diff)
    assert result.diff[3]["after"] == {"start": "2027-03-10", "finish": "2027-03-10"}


# ── 지시문 ──────────────────────────────────────────────────────────


def test_system_prompt_teaches_submitting_and_not_claiming_a_save():
    text = system_prompt()
    assert "out__submit_change 에 draft_id 와 짧은 제목" in text
    assert "저장했다고 말하지 않는다" in text and "out.submit_change" not in text
