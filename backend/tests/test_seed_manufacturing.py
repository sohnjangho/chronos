"""시연 씨앗의 둘째 일정 「가상 부품 공장 — 브래킷 BR-200 2만 개」(생산·L3, Task 40). 실적 없음. LLM 을 부르지 않는다."""

from datetime import date

from sqlalchemy import func, select

from app import seed
from app.harness.checks import check
from app.harness.conditions import Condition
from app.seed import seed_demo
from app.store.schedules import list_records, load
from app.store.tables import LlmCall, ScheduleVersion
from app.store.versions import list_versions
from app.store.view import view_data


def _factory(session):
    m = [r for r in list_records(session) if r.domain == "manufacturing"]
    assert len(m) == 1
    return m[0]


def test_seed_makes_a_factory_schedule(session):
    seed_demo(session)
    seed_demo(session)
    m = _factory(session)
    v = view_data(session, m.id)
    assert 26 <= len(v["activities"]) <= 32 and v["finish"] <= date(2027, 9, 10)
    press = [a for a in v["activities"] if "프레스" in a["tags"]]
    assert any(a["es"] < date(2027, 7, 29) and a["ef"] > date(2027, 8, 4) for a in press)  # 정기 보수를 건너 이어짐
    assert v["calendar"]["blocked"] == [{"tag": "프레스", "start": date(2027, 7, 29), "finish": date(2027, 8, 4)}]


def test_seed_factory_passes_its_checks(session):
    seed_demo(session)
    schedule, conditions, _ = load(session, _factory(session).id)
    report = check(schedule, [Condition.from_dict(c) for c in conditions])
    assert report.violations == [] and report.invalid == []
    assert "in.finish_by" in report.passed and "manufacturing.press_maintenance" in report.passed
    assert "manufacturing.cooling_after_heat" in report.passed


def test_factory_shape(session):
    seed_demo(session)
    m = _factory(session)
    assert (m.name, m.level, m.current_version) == (seed.FACTORY, "L3", 1)
    assert [(v.n, v.is_plan) for v in list_versions(session, m.id)] == [(1, True)]
    schedule, conditions, _ = load(session, m.id)
    assert schedule.start == date(2027, 7, 5) and schedule.data_date is None
    assert {r.id: r.capacity for r in schedule.resources} == {
        "press_line": 1, "heat_furnace": 1, "cnc": 2, "assembly_line": 1, "cmm": 1, "mold_shop": 1}
    assert all(a.actual_start is None and a.progress == 0 for a in schedule.activities)  # 실적 없음
    assert {c["layer"] for c in conditions} == {"base", "domain", "input"}
    inputs = {c["id"]: c for c in conditions if c["layer"] == "input"}
    assert inputs["in.finish_by"]["params"] == {"date": "2027-09-10"}
    assert (inputs["in.finish_by"]["source"], inputs["in.finish_by"]["text"]) == ("질문지", "납기 9월 10일")
    assert inputs["in.resource_cap.press_line"]["params"] == {"resource_id": "press_line", "capacity": 1}


def test_factory_uses_the_pack_wbs_and_resources(session):
    """WBS 는 생산 분야 틀의 코드, 액티비티 자원은 그 공정 유형의 설비, 쓰지 않는 주요 자원은 없다."""
    from app.domains.loader import load as load_pack

    seed_demo(session)
    schedule, _, _ = load(session, _factory(session).id)
    pack = load_pack("manufacturing")
    template = {n.code: n.name for n in pack.wbs_template}
    assert all(template.get(w.code) == w.name for w in schedule.wbs)
    types = {t.tag: set(t.resources) for t in pack.activity_types}
    for a in schedule.activities:
        assert set(a.resources) == set().union(*(types[t] for t in a.tags)), a.id
    assert {r for a in schedule.activities for r in a.resources} == {r.id for r in schedule.resources}


def test_seed_keeps_both_and_calls_no_llm(session):
    seed_demo(session)
    seed_demo(session)
    names = sorted(r.name for r in list_records(session))
    assert names == sorted([seed.OFFICE, seed.FACTORY])
    assert session.scalar(select(func.count()).select_from(ScheduleVersion)) == 3  # 사무동 2 · 공장 1
    assert session.scalar(select(func.count()).select_from(LlmCall)) == 0


def test_factory_twice_is_the_same(session):
    seed_demo(session)
    first = load(session, _factory(session).id)
    seed_demo(session)
    assert load(session, _factory(session).id) == first


def test_cli_says_two(client, session, capsys):
    assert seed.main(["demo"]) == 0
    assert "2개" in capsys.readouterr().out
