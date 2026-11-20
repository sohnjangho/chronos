"""도구 delay.record(지연 기록 — 일정은 그대로)·delay.analyze(지연 영향 묶음)."""

from dataclasses import replace
from datetime import date

import pytest

from app.agent import context
from app.core.model import Relation
from app.store.delays import DelayEventRow
from app.store.schedules import load
from app.store.versions import save_new_version
from app.tools.registry import call, list_tools
from tests.schedules import make, store, task

B2 = {"activity_id": "B", "days": 2, "cause": "우천", "start_date": "2027-03-04"}


@pytest.fixture
def sid3(session) -> int:
    """A 3일 → B 2일, A → C 1일. 준공 3/5."""
    return store(session, make([task("A", 3), task("B", 2), task("C", 1)], [Relation("A", "B"), Relation("A", "C")]))


@pytest.fixture
def ctx3(ctx, sid3):
    return replace(ctx, schedule_id=sid3)


def test_spec():
    specs = {t.name: t for t in list_tools()}
    assert (specs["delay.record"].program, specs["delay.record"].mutates) == ("delays", True)
    assert (specs["delay.analyze"].program, specs["delay.analyze"].mutates) == ("delays", False)


async def test_record_tool_card_and_window(ctx3, events, sid3):
    r = await call("delay.record", B2, ctx3)
    assert r.ok, r.error
    assert [e.data.get("kind", e.type) for e in events] == ["delay_impact", "open_window"]
    assert events[-1].data == {"program": "delays", "params": {"id": str(sid3), "event": "1"}}
    o = r.output
    assert (o["event_id"], o["status"], o["impact"]["finish_delta"], o["totals"]["finish_impact"]) == (1, "open", 2, 2)
    assert events[0].data == {"kind": "delay_impact", "schedule_id": sid3, "event_id": 1, "activity_id": "B",
                              "name": "작업 B", "days": 2, "status": "open", "impact": o["impact"],
                              "totals": o["totals"]}


async def test_record_does_not_touch_the_schedule(ctx3, session, sid3):
    await call("delay.record", B2, ctx3)
    row = session.get(DelayEventRow, 1)
    assert (row.source, row.responsibility, row.daily_cost, row.created_by, row.cause) == (
        "chat", "undecided", None, "관리자", "우천")
    assert load(session, sid3)[2] == 1


async def test_start_date_defaults_to_data_date_then_today(ctx3, session, sid3, monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2027, 3, 2))
    args = {k: v for k, v in B2.items() if k != "start_date"}
    await call("delay.record", args, ctx3)
    assert session.get(DelayEventRow, 1).start_date == date(2027, 3, 2)
    schedule, conditions, _ = load(session, sid3)
    save_new_version(session, sid3, replace(schedule, data_date=date(2027, 3, 3)), conditions, by_kind="user",
                     by_name="관리자", note="Data Date", changes=[], base_version=1)
    await call("delay.record", args, ctx3)
    assert session.get(DelayEventRow, 2).start_date == date(2027, 3, 3)


async def test_actual_source_is_reflected_with_version_diff(ctx3, session, sid3):
    schedule, conditions, _ = load(session, sid3)
    done = {"A": {"actual_start": date(2027, 3, 1), "actual_finish": date(2027, 3, 3), "progress": 1.0},
            "B": {"actual_start": date(2027, 3, 4), "progress": 0.1, "rd": 4}}
    acts = tuple(replace(a, **done.get(a.id, {})) for a in schedule.activities)
    save_new_version(session, sid3, replace(schedule, activities=acts), conditions, by_kind="agent", by_name="에이전트",
                     note="실적", changes=[], base_version=1)
    o = (await call("delay.record", {"activity_id": "B", "days": 2, "cause": "실적 입력에서 감지", "source": "actual",
                                     "before_version": 1}, ctx3)).output
    assert o["status"] == "reflected" and o["impact"]["finish_delta"] == 2
    row = session.get(DelayEventRow, o["event_id"])
    assert (row.source, row.reflected_version, row.analyzed_version) == ("actual", 2, 2)
    assert o["totals"]["open_count"] == 0 and o["totals"]["finish_impact"] == 2


async def test_actual_source_needs_before_version(ctx3):
    r = await call("delay.record", {**B2, "source": "actual"}, ctx3)
    assert r.error == "실적에서 감지한 지연은 before_version 이 필요합니다."


async def test_bad_records(ctx3, ctx, session):
    assert (await call("delay.record", {**B2, "activity_id": "Z"}, ctx3)).error == "없는 액티비티입니다: Z"
    assert (await call("delay.record", {**B2, "source": "actual", "before_version": 9}, ctx3)).error == (
        "없는 버전입니다: 9")
    assert (await call("delay.record", B2, ctx)).error == "대상 일정이 없습니다."
    assert (await call("delay.record", {**B2, "days": 0}, ctx3)).error.startswith("입력 형식 오류")
    assert (await call("delay.record", {**B2, "extra": 1}, ctx3)).error.startswith("입력 형식 오류")
    assert session.query(DelayEventRow).count() == 0


async def test_analyze_tool(ctx3):
    await call("delay.record", B2, ctx3)
    await call("delay.record", {**B2, "activity_id": "C", "days": 1, "start_date": "2027-03-03"}, ctx3)
    o = (await call("delay.analyze", {}, ctx3)).output
    assert o["events"] == [
        {"event_id": 2, "activity_id": "C", "days": 1, "status": "open", "finish_delta": 0, "absorbed": 1},
        {"event_id": 1, "activity_id": "B", "days": 2, "status": "open", "finish_delta": 2, "absorbed": 0},
    ]
    assert (o["finish"]["with_open"], o["finish"]["current"], o["totals"]["absorbed_events"]) == (
        "2027-03-09", "2027-03-05", 1)
