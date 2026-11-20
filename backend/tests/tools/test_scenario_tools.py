"""도구 scenario.create(만약에 복사본 — 일정은 그대로)·scenario.submit(복사본을 승인함으로)."""

from dataclasses import replace

import pytest

from app.core.model import Relation, Resource
from app.store.schedules import load, to_json
from app.store.tables import Approval, Scenario
from app.store.versions import save_new_version
from app.tools.registry import call, list_tools
from tests.approval_doubles import crane
from tests.schedules import make, store, task

STALE = "그 사이 일정이 바뀌었습니다. 일정을 다시 읽고 고쳐 주세요."
B4 = {"name": "B 4일", "base_version": 1, "changes": [{"op": "update_activity", "id": "B", "od": 4}]}


@pytest.fixture
def ctx_sid(ctx, sid):
    """sid(A 3일 → B 2일, 준공 3/5) 를 다루는 문맥."""
    return replace(ctx, schedule_id=sid)


def view(client, admin, sid: int) -> dict:
    return client.get(f"/api/schedules/{sid}", headers=admin).json()


def test_spec():
    specs = {t.name: t for t in list_tools()}
    assert (specs["scenario.create"].program, specs["scenario.create"].mutates) == ("compare", True)
    assert (specs["scenario.submit"].program, specs["scenario.submit"].mutates) == ("approvals", True)


async def test_scenario_does_not_touch_the_schedule(client, admin, session, sid, ctx_sid):
    r = await call("scenario.create", B4, ctx_sid)
    assert r.ok, r.error
    s = r.output["summary"]
    assert (s["finish"], s["finish_delta"]) == ("2027-03-09", 2) and view(client, admin, sid)["version"] == 1
    row = session.get(Scenario, r.output["scenario_id"])
    assert (row.schedule_id, row.base_version, row.name, row.source, row.status, row.created_by) == (
        sid, 1, "B 4일", "agent", "open", "관리자")
    assert session.query(Approval).count() == 0


async def test_scenario_events(ctx_sid, events, sid):
    r = await call("scenario.create", B4, ctx_sid)
    assert [e.data.get("kind", e.type) for e in events] == ["scenario_created", "open_window"]
    assert events[-1].data["params"]["other"].startswith("s:")
    sc = r.output["scenario_id"]
    assert events[0].data == {"kind": "scenario_created", "scenario_id": sc, "schedule_id": sid, "name": "B 4일",
                              "summary": r.output["summary"]}
    assert events[1].data == {"program": "compare", "params": {"id": str(sid), "base": "current", "other": f"s:{sc}"}}


async def test_summary_fields(ctx_sid):
    s = (await call("scenario.create", B4, ctx_sid)).output["summary"]
    assert s == {"finish": "2027-03-09", "finish_delta": 2, "plan_delta": 2, "deadline_float": None, "critical_count": 2,
                 "violations": [], "uncheckable": 0, "peak": None, "changed_count": 1, "gain": None,
                 "base_finish": None, "note": "", "recommended": False}


async def test_peak_is_the_most_loaded_resource_with_its_condition_capacity(ctx, session):
    """A(크레인 1대) → B(리프트 4대 가운데 1). 크레인 2대 조건이면 크레인 1/2 가 리프트 1/4 보다 무겁다."""
    lifts = Resource("a_lift", "리프트", "대", 4)
    s = make([task("A", 3, resources=("crane",)), task("B", 2, resources=("a_lift",))], [Relation("A", "B")],
             [Resource("crane", "타워크레인", "대", 1), lifts])
    cx = replace(ctx, schedule_id=store(session, s))
    r = await call("scenario.create", {**B4, "conditions": [crane(2)]}, cx)
    assert r.output["summary"]["peak"] == {"resource_id": "crane", "name": "타워크레인", "need": 1, "capacity": 2,
                                           "when": "2027-03-01"}


async def test_condition_only_scenario_keeps_the_other_layers(ctx_sid, session):
    r = await call("scenario.create", {"name": "크레인 2대", "base_version": 1, "conditions": [crane(2)]}, ctx_sid)
    assert r.ok, r.error
    assert [d["id"] for d in session.get(Scenario, r.output["scenario_id"]).conditions_json] == ["in.resource_cap.crane"]


@pytest.mark.parametrize(("args", "error"), [
    ({"name": "그대로", "base_version": 1}, "바꾸는 것이 없는 복사본입니다."),
    ({"name": "그대로", "base_version": 1, "changes": [{"op": "update_activity", "id": "B", "od": 2}]},
     "바꾸는 것이 없는 복사본입니다."),
    ({**B4, "base_version": 2}, STALE),
    ({**B4, "changes": [{"op": "update_activity", "id": "Z", "od": 4}]}, "없는 액티비티입니다: Z"),
    ({**B4, "changes": [{"op": "update_activity", "id": "A", "preds": [{"pred": "B"}]}]}, "선후 관계가 고리를 이룹니다."),
    ({**B4, "conditions": [{"id": "x", "layer": "domain", "kind": "text_only", "params": {}, "text": "글", "source": "분야"}]},
     "입력 조건(layer input)만 바꿀 수 있습니다: x"),
])
async def test_bad_scenarios_are_tool_errors_and_save_nothing(ctx_sid, session, args, error):
    r = await call("scenario.create", args, ctx_sid)
    assert (r.ok, r.error) == (False, error)
    assert session.query(Scenario).count() == 0


async def test_create_needs_a_schedule(ctx):
    assert (await call("scenario.create", B4, ctx)).error == "대상 일정이 없습니다."


async def test_submit_tool_sends_the_scenario_to_the_inbox(ctx_sid, session, events, sid):
    sc = (await call("scenario.create", B4, ctx_sid)).output["scenario_id"]
    events.clear()
    r = await call("scenario.submit", {"scenario_id": sc}, ctx_sid)
    assert r.ok, r.error
    aid = r.output["approval_id"]
    assert r.output == {"applied": False, "approval_id": aid, "version": None, "schedule_id": sid,
                        "reasons": ["finish_changed"]}
    row = session.get(Approval, aid)
    assert (row.title, row.link_kind, row.link_id, row.reset_plan) == ("B 4일", "scenario", sc, False)
    assert [e.type for e in events] == ["approval"]
    assert (session.get(Scenario, sc).status, session.get(Scenario, sc).approval_id) == ("submitted", aid)


async def test_submit_tool_title(ctx_sid, session):
    sc = (await call("scenario.create", B4, ctx_sid)).output["scenario_id"]
    r = await call("scenario.submit", {"scenario_id": sc, "title": "만회안 반영"}, ctx_sid)
    assert session.get(Approval, r.output["approval_id"]).title == "만회안 반영"
    refused = await call("scenario.submit", {"scenario_id": sc, "reset_plan": True}, ctx_sid)  # PM 11-20: Plan 다시 잡기 없음
    assert refused.error.startswith("입력 형식 오류: reset_plan")


async def test_submit_tool_refuses_missing_locked_and_stale(ctx_sid, session):
    assert (await call("scenario.submit", {"scenario_id": 999}, ctx_sid)).error == "복사본을 찾을 수 없습니다."
    sc = (await call("scenario.create", B4, ctx_sid)).output["scenario_id"]
    assert (await call("scenario.submit", {"scenario_id": sc}, ctx_sid)).ok
    locked = await call("scenario.submit", {"scenario_id": sc}, ctx_sid)
    assert locked.error == "승인을 기다리거나 반영되었거나 버린 복사본은 낼 수 없습니다."
    session.get(Scenario, sc).status, session.get(Scenario, sc).base_version = "open", 0
    stale = await call("scenario.submit", {"scenario_id": sc}, ctx_sid)
    assert stale.error == "기준 일정이 바뀌었습니다. 복사본을 다시 만들어 주세요."


async def test_submit_tool_refuses_a_copy_of_another_schedule(ctx_sid, ctx, session):               # Fix 1 M1
    sc = (await call("scenario.create", B4, ctx_sid)).output["scenario_id"]
    other = replace(ctx, schedule_id=store(session, make([task("A", 1)])))
    r = await call("scenario.submit", {"scenario_id": sc}, other)
    assert (r.error, session.query(Approval).count()) == ("복사본을 찾을 수 없습니다.", 0)


async def test_submit_tool_explains_an_uncomputable_schedule(ctx_sid, session, sid):                # Fix 1 M2
    """지금 버전이 계산되지 않으면(고리) 도구 오류가 아니라 한국어 설명을 준다."""
    before, stored, _ = load(session, sid)
    broken = replace(before, relations=(*before.relations, Relation("B", "A")))
    save_new_version(session, sid, broken, stored, by_kind="user", by_name="김하늘", note="고리", changes=[],
                     base_version=1, plan_change=True)
    with_b4 = replace(before, activities=tuple(replace(a, od=4) if a.id == "B" else a for a in before.activities))
    row = Scenario(schedule_id=sid, base_version=2, name="B 4일", source="agent",
                   snapshot_json=to_json(with_b4), conditions_json=stored, created_by="김하늘")
    session.add(row)
    session.commit()
    r = await call("scenario.submit", {"scenario_id": row.id}, ctx_sid)
    assert r.error == "선후 관계가 고리를 이룹니다."
