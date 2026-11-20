"""도구 harness.check (R8)."""

from dataclasses import replace

from app.core.model import Relation, Resource
from app.harness.conditions import BASE_RULES, Condition
from app.store.schedules import to_json
from app.store.tables import ScheduleVersion
from app.tools.registry import call, list_tools
from tests.schedules import make, store, task

BASE_IDS = [b.id for b in BASE_RULES]


def test_spec():
    spec = {t.name: t for t in list_tools()}["harness.check"]
    assert (spec.program, spec.mutates) == ("conditions", False) and spec.description


async def test_missing_schedule_id_fails_with_message(ctx):
    r = await call("harness.check", {}, ctx)
    assert (r.ok, r.output, r.error) == (False, None, "대상 일정이 없습니다.")


async def test_unknown_schedule_is_explained(ctx):
    r = await call("harness.check", {}, replace(ctx, schedule_id=999))
    assert (r.ok, r.output, r.error) == (False, None, "일정을 찾을 수 없습니다.")


async def test_extra_arguments_are_rejected(ctx, sid):
    r = await call("harness.check", {"schedule_id": sid}, replace(ctx, schedule_id=sid))
    assert r.ok is False and r.error.startswith("입력 형식 오류: schedule_id: ")


async def test_checks_the_stored_schedule_against_the_assembled_conditions(ctx, session):
    # A(3)·B(2)가 크레인 1대를 같이 쓴다: 맞춘 뒤 B 는 03.04~03.05, 준공 03.05.
    crane = Resource("crane", "타워크레인", "대", 1)
    schedule = make([task("A", 3, resources=("crane",)), task("B", 2, resources=("crane",))], resources=[crane])
    conditions = [
        Condition("base.no_cycle", "base", "no_cycle", {}, "", "기본 규칙", enabled=False),  # 낡은 저장본
        Condition("d1", "domain", "finish_by", {"date": "2027-03-31"}, "준공 3월 안", "분야 규칙"),
        Condition("i1", "input", "finish_by", {"date": "2027-03-04"}, "준공 03.04 이전", "프롬프트"),
        Condition("i2", "input", "text_only", {}, "안전 우선", "프롬프트"),
        Condition("i3", "input", "resource_cap", {"resource_id": "crane", "capacity": 1}, "크레인 1대", "프롬프트"),
    ]
    sid = store(session, schedule, conditions=[c.to_dict() for c in conditions])
    r = await call("harness.check", {}, replace(ctx, schedule_id=sid))
    assert (r.ok, r.error) == (True, None)
    assert r.output == {
        "passed": [*BASE_IDS, "i3"],
        "violations": [
            {"condition_id": "i1", "message": "준공이 기한보다 1일 늦습니다.", "activity_ids": ["B"], "amount": 1}
        ],
        "notices": [
            {
                "condition_id": "i3",
                "message": "맞추기 전 날짜로는 타워크레인 필요량이 용량(1대)을 넘는 날이 2일 있습니다(최대 1대 초과).",
                "activity_ids": ["A", "B"],
                "amount": 1,
            }
        ],
        "uncheckable": ["i2"],
        "skipped": [],
        "invalid": [],
    }


async def test_broken_stored_schedule_is_reported_not_raised(ctx, session, sid):
    cycle = make([task("A", 1), task("B", 1)], [Relation("A", "B"), Relation("B", "A")])
    session.get(ScheduleVersion, (sid, 1)).snapshot_json = to_json(cycle)
    session.commit()
    r = await call("harness.check", {}, replace(ctx, schedule_id=sid))
    assert r.ok is True
    assert r.output == {
        "passed": [],
        "violations": [
            {"condition_id": "base.no_cycle", "message": "선후 관계가 고리를 이룹니다.", "activity_ids": ["A", "B"],
             "amount": None}
        ],
        "notices": [],
        "uncheckable": [],
        "skipped": BASE_IDS[1:],
        "invalid": [],
    }


# ── fix round 1 ─────────────────────────────────────────────────────


async def test_unreadable_stored_conditions_are_reported_not_raised(ctx, session, sample_schedule):
    # tests/tools/test_first_tools.py 가 저장하는 모양: id 만 있는 조건 둘 (F1)
    sid = store(session, sample_schedule, conditions=[{"id": "c1"}, {"id": "c2"}])
    r = await call("harness.check", {}, replace(ctx, schedule_id=sid))
    assert (r.ok, r.error) == (True, None)
    assert r.output["invalid"] == [
        {"condition_id": "c1", "message": "'kind' 칸이 없습니다."},
        {"condition_id": "c2", "message": "'kind' 칸이 없습니다."},
    ]
    assert r.output["passed"] == BASE_IDS and r.output["violations"] == []


async def test_a_bad_stored_condition_does_not_stop_the_others(ctx, session, sample_schedule):
    bad = Condition("i1", "input", "finish_by", {"date": "2027-03-04"}, "", "프롬프트").to_dict()
    bad["params"] = {"date": "3월 4일"}
    good = Condition("i2", "input", "finish_by", {"date": "2027-03-04"}, "", "프롬프트").to_dict()
    sid = store(session, sample_schedule, conditions=[bad, {"layer": "input"}, good])
    r = await call("harness.check", {}, replace(ctx, schedule_id=sid))
    assert r.output["invalid"] == [
        {"condition_id": "i1", "message": "'date' 칸 값이 올바르지 않습니다: 날짜(YYYY-MM-DD)"},
        {"condition_id": "?", "message": "'id' 칸이 없습니다."},
    ]
    assert [v["condition_id"] for v in r.output["violations"]] == ["i2"]


async def test_check_and_the_screen_use_the_same_schedule(client, admin, ctx, session):
    # 검토 예 (F4): 저장된 크레인 1대, 입력 조건 2대, 준공 03.05. 조건을 넣으면 A·B 가 같이 일해 준공 03.03.
    crane = Resource("crane", "타워크레인", "대", 1)
    schedule = make([task("A", 3, resources=("crane",)), task("B", 3, resources=("crane",))], resources=[crane])
    conditions = [
        Condition("i1", "input", "resource_cap", {"resource_id": "crane", "capacity": 2}, "크레인 2대", "프롬프트"),
        Condition("i2", "input", "finish_by", {"date": "2027-03-05"}, "준공 03.05", "프롬프트"),
    ]
    sid = store(session, schedule, conditions=[c.to_dict() for c in conditions])
    sctx = replace(ctx, schedule_id=sid)
    report = (await call("harness.check", {}, sctx)).output
    assert report["violations"] == [] and report["passed"] == [*BASE_IDS, "i1", "i2"]
    view = client.get(f"/api/schedules/{sid}", headers=admin).json()
    assert view["finish"] == "2027-03-03"
    assert (await call("calc.cpm", {}, sctx)).output["finish"] == "2027-03-03"
    assert (await call("schedule.read", {}, sctx)).output["finish"] == "2027-03-03"
    # 고친 뒤(버전 2)에도 지금 날짜와 Plan(이름 고침도 계획 변경이라 버전 2 때 찍은 것) 날짜 모두 조건을 넣어 계산한다.
    patched = client.patch(
        f"/api/schedules/{sid}/activities/A", json={"name": "기초", "base_version": 1}, headers=admin
    ).json()
    assert (patched["version"], patched["finish"], patched["plan_finish"]) == (2, "2027-03-03", "2027-03-03")
