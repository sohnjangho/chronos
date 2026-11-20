# ruff: noqa: F811
"""생산 분야 묶음(manufacturing/pack.yaml)과 분야별 표시 설정(DisplaySpec)."""

from datetime import date

import pytest

from app.agent.context import system_prompt
from app.agent.generation import generate
from app.core.cpm import compute
from app.core.model import Activity, CalendarSpec, Relation, Schedule, WbsNode
from app.domains.loader import DisplaySpec, domains, load
from app.harness.assemble import assemble, prepare
from app.harness.checks import check
from app.harness.conditions import Condition
from tests.agent.conftest import ctx, events, liner, llm  # noqa: F401  (생성 시험용 fixture)
from tests.gen_doubles import act, script

MFG_WBS = {
    "wbs": [
        {"code": "1", "name": "브래킷 주문", "parent": None},
        {"code": "1.1", "name": "생산", "parent": "1"},
        {"code": "1.1.1", "name": "프레스", "parent": "1.1"},
    ]
}
MFG_SCHED = {
    "activities": [
        act("A1000", "착수", "1.1.1", 0, kind="start_ms"),
        act("A1010", "브래킷 블랭킹", "1.1.1", 5, ["A1000"]),
        act("A1020", "납기", "1.1.1", 0, ["A1010"], kind="finish_ms"),
    ]
}


def _rules() -> list[Condition]:
    return [Condition.from_dict(d) for d in load("manufacturing").rules_raw]


def heat_then_machine(lag: int) -> Schedule:
    """열처리 2일(3/1~3/2) → 가공 1일. lag 만큼 사이를 띄운다."""
    return Schedule(
        date(2027, 3, 1),
        CalendarSpec(5),
        (WbsNode("3", "생산", None),),
        (
            Activity("H1", "담금질", "task", "3", 2, tags=("열처리",)),
            Activity("M1", "CNC 가공", "task", "3", 1, tags=("가공",)),
        ),
        (Relation("H1", "M1", "FS", lag),),
    )


def test_both_domains():
    assert domains() == ["construction", "manufacturing"]


def test_pack_reads():
    p = load("manufacturing")
    assert p.name == "생산"
    assert [Condition.from_dict(r).kind for r in p.rules_raw] == ["blocked_period", "min_gap", "text_only", "text_only", "text_only"]


def test_resources_and_types_link():
    p = load("manufacturing")
    assert {r.id for r in p.key_resources} == {"press_line", "heat_furnace", "cnc", "assembly_line", "cmm", "mold_shop"}
    assert next(t for t in p.activity_types if t.tag == "프레스").resources == ["press_line"]


def test_display():
    assert load("manufacturing").display == DisplaySpec(gantt_group_by="resource", deadline_label="납기", extra_columns=["resources"])
    assert load("construction").display.deadline_label == "준공"
    assert DisplaySpec() == DisplaySpec(gantt_group_by="wbs", deadline_label="준공", extra_columns=[])


def test_press_maintenance_blocks_press_work():
    s = Schedule(
        date(2027, 7, 28), CalendarSpec(5), (WbsNode("3", "생산", None),),
        (Activity("P1", "브래킷 블랭킹", "task", "3", 3, tags=("프레스",)),), (),
    )
    r = compute(prepare(s, _rules()))
    assert (r.rows["P1"].es, r.rows["P1"].ef) == (date(2027, 7, 28), date(2027, 8, 6))


@pytest.mark.parametrize("lag,ok", [(0, False), (1, True)])
def test_cooling_gap_is_checked(lag, ok):
    rep = check(heat_then_machine(lag), assemble(_rules(), [], []))
    assert ("manufacturing.cooling_after_heat" in rep.passed) is ok


def test_prompt_mentions():
    p = load("manufacturing").prompt()
    assert p.startswith("분야: 생산 (manufacturing)") and "납기" in p
    assert "business" in p  # 공급사·부품 리드타임은 업무 검색으로 찾는다(PM 11-20)


async def test_generation_attaches_press_line(ctx, llm, liner):
    script(liner, MFG_WBS, MFG_SCHED)
    r = await generate(
        ctx, llm, domain="manufacturing", level="L3", request="브래킷 2만 개 주문 일정",
        facts=[{"label": "착수일", "value": "2027-03-02", "source": "프롬프트"}],
    )
    assert "press_line" in next(a for a in r.schedule.activities if "블랭킹" in a.name).resources


def test_system_prompt_lists_both():
    assert "construction(건설), manufacturing(생산)" in system_prompt()
