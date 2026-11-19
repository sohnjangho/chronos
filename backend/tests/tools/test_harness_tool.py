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
    }
