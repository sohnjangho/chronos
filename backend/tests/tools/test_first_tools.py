"""첫 도구 셋: schedule.read · calc.cpm · ui.open_window."""

from dataclasses import replace

import pytest

from app.agent.events import AgentEvent
from app.core.model import Relation, Resource
from app.store.schedules import to_json
from app.store.tables import ScheduleVersion
from app.tools.registry import call, list_tools
from tests.schedules import make, store, task

# ── 작업 지시서의 시험 ──────────────────────────────────────────────


async def test_open_window_emits_event(ctx, events):
    await call("ui.open_window", {"program": "schedule", "params": {"tab": "gantt"}}, ctx)
    assert events[-1].type == "open_window" and events[-1].data["program"] == "schedule"


# ── 덧붙인 시험 ─────────────────────────────────────────────────────


@pytest.fixture
def sched_ctx(ctx, sid):
    """sample_schedule(A 3일 → B 2일)을 대상으로 하는 문맥."""
    return replace(ctx, schedule_id=sid)


def test_specs():
    specs = {t.name: t for t in list_tools()}
    assert (specs["schedule.read"].program, specs["schedule.read"].mutates) == ("schedule", False)
    assert (specs["calc.cpm"].program, specs["calc.cpm"].mutates) == ("schedule", False)
    assert (specs["ui.open_window"].program, specs["ui.open_window"].mutates) == (None, False)
    assert all(specs[n].description for n in ("schedule.read", "calc.cpm", "ui.open_window"))


async def test_open_window_output_and_event(ctx, events):
    r = await call("ui.open_window", {"program": "schedule", "params": {"tab": "gantt"}}, ctx)
    assert (r.ok, r.output) == (True, {"opened": True})
    assert events == [AgentEvent("open_window", {"program": "schedule", "params": {"tab": "gantt"}})]
    r = await call("ui.open_window", {"program": "chat"}, ctx)
    assert r.ok and events[-1].data == {"program": "chat", "params": {}}


async def test_open_window_rejects_bad_input(ctx, events):
    assert (await call("ui.open_window", {}, ctx)).ok is False
    assert (await call("ui.open_window", {"program": "x", "params": {"n": {"a": 1}}}, ctx)).ok is False
    assert events == []


async def test_open_window_rejects_a_misspelled_field(ctx, events):
    r = await call("ui.open_window", {"program": "schedule", "param": {"tab": "gantt"}}, ctx)
    assert r.ok is False and r.error.startswith("입력 형식 오류: param: ") and events == []


async def test_schedule_read_summary(sched_ctx, events):
    r = await call("schedule.read", {}, sched_ctx)
    assert r.ok is True and r.error is None and events == []
    assert r.output == {
        "name": "시험 일정",
        "domain": "construction",
        "level": "L3",
        "version": 1,
        "finish": "2027-03-05",
        "activity_count": 2,
        "critical": ["A", "B"],
        "condition_count": 0,
        "summary": {"critical_count": 2, "negative_float_count": 0, "warning_count": 0},
    }


async def test_schedule_read_counts_conditions_and_only_critical_ids(ctx, session):
    # A(3) → B(2), C(1) 은 따로: C 는 여유가 있다.
    schedule = make([task("A", 3), task("B", 2), task("C", 1)], [Relation("A", "B")])
    sid = store(session, schedule, conditions=[{"id": "c1"}, {"id": "c2"}])
    r = await call("schedule.read", {}, replace(ctx, schedule_id=sid))
    assert r.output["critical"] == ["A", "B"] and r.output["activity_count"] == 3
    assert r.output["condition_count"] == 2 and r.output["summary"]["critical_count"] == 2


async def test_schedule_read_matches_schedule_api(client, admin, sched_ctx, sid):
    view = client.get(f"/api/schedules/{sid}", headers=admin).json()
    out = (await call("schedule.read", {}, sched_ctx)).output
    assert out["finish"] == view["finish"] and out["summary"] == {k: view["summary"][k] for k in out["summary"]}
    assert out["critical"] == [a["id"] for a in view["activities"] if a["critical"]]


@pytest.mark.parametrize("name", ["schedule.read", "calc.cpm"])
async def test_missing_schedule_id_fails_with_message(ctx, name):
    r = await call(name, {}, ctx)
    assert (r.ok, r.output, r.error) == (False, None, "대상 일정이 없습니다.")


@pytest.mark.parametrize("name", ["schedule.read", "calc.cpm"])
async def test_unknown_schedule_is_explained(ctx, name):
    r = await call(name, {}, replace(ctx, schedule_id=999))
    assert (r.ok, r.output, r.error) == (False, None, "일정을 찾을 수 없습니다.")


CYCLE = make([task("A", 1), task("B", 1)], [Relation("A", "B"), Relation("B", "A")])


@pytest.mark.parametrize("name", ["schedule.read", "calc.cpm"])
async def test_uncomputable_schedule_is_explained(sched_ctx, session, sid, name):
    session.get(ScheduleVersion, (sid, 1)).snapshot_json = to_json(CYCLE)
    session.commit()
    r = await call(name, {}, sched_ctx)
    assert (r.ok, r.output, r.error) == (False, None, "선후 관계가 고리를 이룹니다.")


@pytest.mark.parametrize("name", ["schedule.read", "calc.cpm"])
async def test_extra_arguments_are_rejected(sched_ctx, name):
    r = await call(name, {"schedule_id": 99}, sched_ctx)
    assert r.ok is False and r.error.startswith("입력 형식 오류")


async def test_calc_cpm_rows(sched_ctx):
    r = await call("calc.cpm", {}, sched_ctx)
    assert r.ok is True
    assert r.output == {
        "finish": "2027-03-05",
        "activities": [
            {"id": "A", "es": "2027-03-01", "ef": "2027-03-03", "ls": "2027-03-01", "lf": "2027-03-03",
             "tf": 0, "ff": 0, "critical": True},
            {"id": "B", "es": "2027-03-04", "ef": "2027-03-05", "ls": "2027-03-04", "lf": "2027-03-05",
             "tf": 0, "ff": 0, "critical": True},
        ],
    }


async def test_calc_cpm_uses_resource_leveling_like_the_view(client, admin, ctx, session):
    # 크레인 1대를 A·B 가 같이 쓴다: 맞춤 뒤에는 하나가 뒤로 밀린다.
    crane = Resource("crane", "타워크레인", "대", 1)
    schedule = make([task("A", 3, resources=("crane",)), task("B", 2, resources=("crane",))], resources=[crane])
    sid = store(session, schedule)
    view = client.get(f"/api/schedules/{sid}", headers=admin).json()
    out = (await call("calc.cpm", {}, replace(ctx, schedule_id=sid))).output
    assert out["finish"] == view["finish"] == "2027-03-05"
    assert [(a["id"], a["es"], a["ef"], a["tf"], a["critical"]) for a in out["activities"]] == [
        (a["id"], a["es"], a["ef"], a["tf"], a["critical"]) for a in view["activities"]
    ]
