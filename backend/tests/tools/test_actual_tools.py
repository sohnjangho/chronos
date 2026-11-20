"""도구 schedule.find(액티비티 찾기)·schedule.record_actual(실적 입력 — 바로 반영, 되돌릴 수 있음)."""

from dataclasses import replace
from datetime import date

import pytest

from app.agent import context
from app.core.model import Relation
from app.store.schedules import load
from app.store.tables import Approval
from app.tools.registry import call, list_tools
from tests.schedules import make, store, task

DD = "2027-03-03"


@pytest.fixture
def sid_ab(session) -> int:
    """A 5일 → B 5일. 버전 1 Plan: A 3/1~3/5, B 3/8~3/12."""
    return store(session, make([task("A", 5), task("B", 5)], [Relation("A", "B")]))


@pytest.fixture
def ctx_ab(ctx, sid_ab):
    return replace(ctx, schedule_id=sid_ab)


def current_version(session, sid: int) -> int:
    return load(session, sid)[2]


async def record(args: dict, ctx) -> dict:
    r = await call("schedule.record_actual", args, ctx)
    assert r.ok, r.error
    return r.output


def test_spec():
    specs = {t.name: t for t in list_tools()}
    assert (specs["schedule.find"].program, specs["schedule.find"].mutates) == ("schedule-table", False)
    assert (specs["schedule.record_actual"].program, specs["schedule.record_actual"].mutates) == (
        "schedule-table", True)


# --- 지시서 시험 -------------------------------------------------------------------------------------------


async def test_progress_fills_start_and_remaining(ctx_ab):
    o = await record({"activity_id": "A", "progress": 0.6, "data_date": DD}, ctx_ab)
    a = o["activity"]
    assert (a["actual_start"], a["rd"], a["ef"], o["delay"]) == ("2027-03-01", 2, "2027-03-04", None)
    assert o["assumed"][0] == "실제 시작일을 2027-03-01로 두었습니다(계획 시작일)." and o["applied"] is True
    assert "남은 기간을 2일로 두었습니다(원래 기간 × (1 − 진도))." in o["assumed"]


async def test_late_progress_reports_delay(ctx_ab):
    o = await record({"activity_id": "A", "progress": 0.2, "data_date": DD}, ctx_ab)
    assert o["delay"] == {"activity_id": "A", "late_days": 1, "finish_delta": 1}
    assert (o["before_version"], o["after_version"], o["version"]) == (1, 2, 2)
    assert o["finish"] == {"before": "2027-03-12", "after": "2027-03-15"}


async def test_actual_input_is_auto_applied_with_undo(ctx_ab, session):
    o = await record({"activity_id": "A", "progress": 0.2, "data_date": DD}, ctx_ab)
    row = session.get(Approval, o["approval_id"])
    assert row.status == "auto" and row.restore_to == 1 and "finish_changed" in row.reasons_json
    assert (row.kind, row.title, row.requested_kind) == ("change", "A 실적 20%", "agent")


async def test_actual_after_data_date_is_refused(ctx_ab, session, sid_ab):
    r = await call("schedule.record_actual", {"activity_id": "A", "actual_finish": "2027-03-10", "data_date": DD}, ctx_ab)
    assert r.error == "실적 날짜가 Data Date(2027-03-03)보다 뒤일 수 없습니다."
    assert current_version(session, sid_ab) == 1


async def test_done_without_finish_uses_data_date(ctx_ab):
    o = await record({"activity_id": "A", "progress": 1, "data_date": DD}, ctx_ab)
    assert o["activity"]["actual_finish"] == DD and o["activity"]["progress"] == 1
    assert "실제 종료일을 Data Date 2027-03-03로 두었습니다." in o["assumed"]


async def test_missing_data_date_uses_today(ctx_ab, monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2027, 3, 3))
    assert (await record({"activity_id": "A", "progress": 0.6}, ctx_ab))["data_date"] == DD


async def test_find_by_id_then_name(ctx_ab):
    assert [m["id"] for m in (await call("schedule.find", {"query": "b"}, ctx_ab)).output["matches"]] == ["B"]


async def test_unknown_activity(ctx_ab):
    r = await call("schedule.record_actual", {"activity_id": "Z", "progress": 0.5}, ctx_ab)
    assert r.error == "없는 액티비티입니다: Z"


# --- 더한 시험 ---------------------------------------------------------------------------------------------


async def test_data_date_argument_moves_the_schedule_data_date(ctx_ab, session, sid_ab):
    await record({"activity_id": "A", "progress": 0.6, "data_date": DD}, ctx_ab)
    schedule, _, n = load(session, sid_ab)
    assert (schedule.data_date, n) == (date(2027, 3, 3), 2)


async def test_schedule_data_date_is_used_before_today(ctx_ab, session, sid_ab, monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2027, 4, 1))
    await record({"activity_id": "A", "progress": 0.6, "data_date": DD}, ctx_ab)  # 일정 Data Date 3/3
    o = await record({"activity_id": "B", "actual_start": "2027-03-03"}, ctx_ab)
    assert o["data_date"] == DD and load(session, sid_ab)[0].data_date == date(2027, 3, 3)


async def test_start_after_plan_uses_data_date(ctx_ab):
    o = await record({"activity_id": "B", "progress": 0.2, "data_date": DD}, ctx_ab)  # B ES 3/8 > DD
    assert o["activity"]["actual_start"] == DD
    assert o["assumed"][0] == "실제 시작일을 2027-03-03로 두었습니다(Data Date)."


async def test_actual_finish_sets_progress_one(ctx_ab):
    o = await record({"activity_id": "A", "actual_start": "2027-03-01", "actual_finish": "2027-03-02", "data_date": DD},
                     ctx_ab)
    a = o["activity"]
    assert (a["progress"], a["actual_start"], a["actual_finish"], a["status"], a["rd"]) == (
        1, "2027-03-01", "2027-03-02", "done", None)
    assert o["assumed"] == [] and o["delay"] is None


async def test_finish_before_start_is_refused(ctx_ab, session, sid_ab):
    r = await call("schedule.record_actual", {"activity_id": "A", "actual_start": "2027-03-02",
                                              "actual_finish": "2027-03-01", "data_date": DD}, ctx_ab)
    assert r.error == "실제 종료일이 실제 시작일보다 앞설 수 없습니다." and current_version(session, sid_ab) == 1


async def test_milestone_progress_must_be_zero_or_one(ctx, session):
    ms = task("M", 0, kind="finish_ms")
    sid = store(session, make([task("A", 5), ms], [Relation("A", "M")]))
    r = await call("schedule.record_actual", {"activity_id": "M", "progress": 0.5, "data_date": DD},
                   replace(ctx, schedule_id=sid))
    assert r.error == "마일스톤은 진도 0 또는 1만 넣을 수 있습니다."


async def test_one_of_the_actuals_is_required(ctx_ab):
    r = await call("schedule.record_actual", {"activity_id": "A", "data_date": DD}, ctx_ab)
    assert r.error.startswith("입력 형식 오류")


async def test_card_event(ctx_ab, events, sid_ab):
    o = await record({"activity_id": "A", "progress": 0.2, "data_date": DD}, ctx_ab)
    assert [e.data.get("kind", e.type) for e in events] == ["actual_recorded"]
    assert events[0].data == {"kind": "actual_recorded", "schedule_id": sid_ab, "activity_id": "A", "name": "작업 A",
                              "progress": 0.2, "assumed": o["assumed"], "delay": o["delay"], "version": 2}


async def test_same_actual_again_is_no_change(ctx_ab):
    await record({"activity_id": "A", "progress": 0.6, "data_date": DD}, ctx_ab)
    r = await call("schedule.record_actual", {"activity_id": "A", "progress": 0.6, "data_date": DD}, ctx_ab)
    assert r.error == "바뀌는 것이 없습니다."


async def test_no_target_schedule(ctx):
    r = await call("schedule.record_actual", {"activity_id": "A", "progress": 0.5}, ctx)
    assert r.error == "대상 일정이 없습니다."


async def test_find_output_and_order(ctx, session):
    acts = [task("A1", 2, name="골조 1층"), task("A2", 2, name="골조 2층"), task("X", 1, name="a2 점검")]
    sid = store(session, make(acts, [Relation("A1", "A2"), Relation("A2", "X")]))
    c = replace(ctx, schedule_id=sid)
    found = (await call("schedule.find", {"query": "A2"}, c)).output["matches"]
    assert [m["id"] for m in found] == ["A2", "X"]  # id 가 같은 것 먼저, 그다음 이름에 든 것
    assert found[0] == {"id": "A2", "name": "골조 2층", "wbs": "1", "kind": "task", "es": "2027-03-03",
                        "ef": "2027-03-04", "plan_start": "2027-03-03", "plan_finish": "2027-03-04", "progress": 0.0,
                        "actual_start": None, "actual_finish": None, "status": "on_plan", "tf": 0}
    names = (await call("schedule.find", {"query": "골조 층", "limit": 1}, c)).output["matches"]
    assert names == []  # 공백을 뺀 이름("골조1층")에 공백 뺀 query("골조층")가 들어 있어야 한다
    assert [m["id"] for m in (await call("schedule.find", {"query": "골조", "limit": 1}, c)).output["matches"]] == ["A1"]


async def test_find_nothing(ctx_ab):
    assert (await call("schedule.find", {"query": "없는것"}, ctx_ab)).output == {"matches": []}


# --- Fix round 1 -------------------------------------------------------------------------------------------


async def test_no_data_date_saves_today_to_the_schedule(ctx_ab, session, sid_ab, monkeypatch):  # I1
    monkeypatch.setattr(context, "today", lambda: date(2027, 3, 3))
    o = await record({"activity_id": "A", "progress": 0.2}, ctx_ab)
    assert (o["activity"]["ef"], o["activity"]["status"]) == ("2027-03-08", "late +1")
    assert o["delay"] == {"activity_id": "A", "late_days": 1, "finish_delta": 1}
    assert o["assumed"][0] == "Data Date를 오늘(2027-03-03)로 두었습니다."
    assert load(session, sid_ab)[0].data_date == date(2027, 3, 3)


async def test_milestone_done_starts_on_its_finish(ctx, session):  # M1
    sid = store(session, make([task("A", 5), task("M", 0, kind="finish_ms")], [Relation("A", "M")]))
    o = await record({"activity_id": "M", "progress": 1, "data_date": DD}, replace(ctx, schedule_id=sid))
    assert (o["activity"]["actual_start"], o["activity"]["actual_finish"]) == (DD, DD)
    assert o["assumed"] == ["실제 종료일을 Data Date 2027-03-03로 두었습니다."]


async def test_finish_only_fills_a_start_not_after_the_finish(ctx_ab):  # M2: B ES 3/8 > DD 3/3
    o = await record({"activity_id": "B", "actual_finish": "2027-03-02", "data_date": DD}, ctx_ab)
    assert (o["activity"]["actual_start"], o["activity"]["actual_finish"]) == ("2027-03-02", "2027-03-02")
    assert o["assumed"] == ["실제 시작일을 2027-03-02로 두었습니다(실제 종료일)."]


async def test_data_date_out_of_range_is_refused(ctx_ab, session, sid_ab):  # M3
    r = await call("schedule.record_actual", {"activity_id": "A", "progress": 0.5, "data_date": "2200-01-01"}, ctx_ab)
    assert r.error.startswith("입력 형식 오류: data_date") and current_version(session, sid_ab) == 1
