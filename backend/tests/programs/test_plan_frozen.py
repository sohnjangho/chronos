"""Task 16e (PM 결정 11-20 밤): Plan = 마지막 '계획 변경' 때의 예측(그때까지의 실적을 담은 계산)으로 고정한다.

계획 변경(Plan 을 새로 찍음): 첫 저장·조건 확정·일정 범위 규칙 승인·단축안 반영·계획 칸 고침·에이전트 고침·되돌리기(그 버전 Plan).
계획 변경 아님(앞 Plan 을 물려받음): 실적 입력·Data Date·지연 반영안 반영.

작은 일정 late(): A 5일 → B 5일, 3/1(월) 시작, 주 5일. A 는 3/1 에 시작해 진도 0.2·남은 6일, Data Date 3/3.
첫 저장이 찍는 Plan = 그때의 예측: A 3/1~3/10(3/3 부터 6일), B 3/11~3/17. 실적을 뺀 계산(16c)이면 A 3/1~3/5, B 3/8~3/12 다.
"""

from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import select

from app.core.model import Relation
from app.llm import fake
from app.seed.office import office_building
from app.store import scenarios
from app.store.delays import DelayEventRow, delayed_base
from app.store.schedules import load
from app.store.settings import set_approval_mode
from app.store.tables import ScheduleVersion, User
from app.store.versions import save_new_version
from app.tools import registry
from app.tools.context import ToolContext
from tests.approval_doubles import finish_by
from tests.llm_doubles import add_connection
from tests.schedules import make, store, task

SNAPPED = [("A", "2027-03-01", "2027-03-10"), ("B", "2027-03-11", "2027-03-17")]  # 첫 저장 때의 예측


def late():
    a = task("A", 5, actual_start=date(2027, 3, 1), progress=0.2, rd=6)
    return replace(make([a, task("B", 5)], [Relation("A", "B")]), data_date=date(2027, 3, 3))


def _view(client, headers, sid):
    r = client.get(f"/api/schedules/{sid}", headers=headers)
    assert r.status_code == 200, r.json()
    return r.json()


def _plan(view):
    return [(a["id"], a["plan_start"], a["plan_finish"]) for a in view["activities"]]


def _status(view):
    return {a["id"]: a["status"] for a in view["activities"]}


def _decide(client, headers, approval_id):
    r = client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "approve", "note": ""}, headers=headers)
    assert r.status_code == 200, r.json()
    return r.json()


def _ctx(session, sid: int, events: list | None = None) -> ToolContext:
    registry.load_all()
    admin = session.scalars(select(User).where(User.login_id == "admin")).one()
    return ToolContext(session=session, user=admin, schedule_id=sid, emit=(events if events is not None else []).append)


async def _tool(session, sid: int, name: str, args: dict) -> dict:
    r = await registry.call(name, args, _ctx(session, sid))
    assert r.ok, r.error
    session.commit()
    return r.output


@pytest.fixture
def sid_late(session) -> int:
    return store(session, late(), [finish_by("2027-04-30")])


def test_first_save_snaps_the_forecast_with_its_actuals(client, admin, sid_late):
    v = _view(client, admin, sid_late)
    assert _plan(v) == SNAPPED and v["plan_finish"] == v["finish"] == "2027-03-17"
    assert _status(v) == {"A": "on_plan", "B": "on_plan"}


# ── 계획 변경 아님: Plan 그대로 ──────────────────────────────────────────


async def test_recording_an_actual_keeps_the_plan(client, admin, session, sid_late):
    # 진도 0.25·Data Date 3/8 → 남은 4일(3/8~3/11), B 3/12~3/18: 둘 다 하루 늦음
    await _tool(session, sid_late, "schedule.record_actual", {"activity_id": "A", "progress": 0.25, "data_date": "2027-03-08"})
    v = _view(client, admin, sid_late)
    assert v["version"] == 2 and _plan(v) == SNAPPED and v["plan_finish"] == "2027-03-17"
    assert (v["finish"], _status(v)) == ("2027-03-18", {"A": "late +1", "B": "late +1"})


def test_a_data_date_or_table_actuals_keep_the_plan(client, admin, sid_late):
    v = client.patch(f"/api/schedules/{sid_late}", json={"data_date": "2027-03-05", "base_version": 1}, headers=admin).json()
    assert _plan(v) == SNAPPED and _status(v) == {"A": "late +2", "B": "late +2"}  # A 3/5~3/12, B 3/15~3/19
    v = client.patch(f"/api/schedules/{sid_late}/activities/A", json={"rd": 7, "progress": 0.1, "base_version": 2},
                     headers=admin).json()
    assert _plan(v) == SNAPPED and _status(v) == {"A": "late +3", "B": "late +3"}


def test_applying_a_delay_copy_keeps_the_plan(client, admin, session, sid_late):
    session.add(DelayEventRow(schedule_id=sid_late, activity_id="B", start_date=date(2027, 3, 3), days=2, created_by="김하늘"))
    session.commit()
    d = delayed_base(session, sid_late)
    sc = scenarios.create(session, schedule_id=sid_late, base_version=d.version, name="지연 반영안 (1건)", source="delay",
                          schedule=d.schedule, conditions=d.conditions, delay_event_ids=d.event_ids, created_by="김하늘")
    session.commit()
    sent = client.post(f"/api/schedules/{sid_late}/scenarios/{sc.id}/submit", json={}, headers=admin).json()
    if not sent["applied"]:
        _decide(client, admin, sent["approval_id"])
    v = _view(client, admin, sid_late)
    assert v["version"] == 2 and _plan(v) == SNAPPED and _status(v)["B"] == "late +2"


# ── 계획 변경: 그때의 예측(실적 포함)으로 다시 찍음 ─────────────────────


def _later(client, admin, sid) -> None:
    """Data Date 를 3/5 로 — 계획 변경 전에 늦음(+2)을 만든다. A 3/1~3/12, B 3/15~3/19."""
    v = client.patch(f"/api/schedules/{sid}", json={"data_date": "2027-03-05", "base_version": 1}, headers=admin).json()
    assert _status(v) == {"A": "late +2", "B": "late +2"}


def test_editing_od_snaps_the_forecast_with_actuals(client, admin, sid_late):
    _later(client, admin, sid_late)
    v = client.patch(f"/api/schedules/{sid_late}/activities/B", json={"od": 4, "base_version": 2}, headers=admin).json()
    assert _plan(v) == [("A", "2027-03-01", "2027-03-12"), ("B", "2027-03-15", "2027-03-18")]
    assert v["plan_finish"] == v["finish"] == "2027-03-18" and _status(v) == {"A": "on_plan", "B": "on_plan"}


def test_editing_plan_and_actual_cells_together_is_a_plan_change(client, admin, sid_late):
    _later(client, admin, sid_late)
    v = client.patch(f"/api/schedules/{sid_late}/activities/A", json={"od": 6, "rd": 7, "base_version": 2},
                     headers=admin).json()
    assert _plan(v) == [("A", "2027-03-01", "2027-03-15"), ("B", "2027-03-16", "2027-03-22")]
    assert _status(v) == {"A": "on_plan", "B": "on_plan"}


def test_committing_conditions_snaps_the_forecast(client, admin, sid_late):
    _later(client, admin, sid_late)
    body = {"base_version": 2, "changes": [{"id": "in.finish_by", "params": {"date": "2027-05-31"}}]}
    r = client.post(f"/api/schedules/{sid_late}/conditions/commit", json=body, headers=admin).json()
    if not r["applied"]:
        _decide(client, admin, r["approval_id"])
    v = _view(client, admin, sid_late)
    assert v["version"] == 3 and _plan(v) == [("A", "2027-03-01", "2027-03-12"), ("B", "2027-03-15", "2027-03-19")]
    assert _status(v) == {"A": "on_plan", "B": "on_plan"}


async def test_approving_text_only_schedule_rule_keeps_plan(client, admin, session, sid_late):
    _later(client, admin, sid_late)
    o = await _tool(session, sid_late, "rules.propose", {
        "scope": "schedule", "condition": {"kind": "text_only", "params": {}, "text": "타설 전날 알림"}, "why": "늘 그렇게"})
    if not o["applied"]:
        _decide(client, admin, o["approval_id"])
    v = _view(client, admin, sid_late)
    assert v["version"] == 3 and _plan(v) == SNAPPED and _status(v) == {"A": "late +2", "B": "late +2"}


async def test_approving_date_changing_schedule_rule_snaps_the_forecast(client, admin, session, sid_late):
    _later(client, admin, sid_late)
    o = await _tool(session, sid_late, "rules.propose", {
        "scope": "schedule",
        "condition": {"kind": "calendar", "params": {"days_per_week": 7, "holidays": []}, "text": "주 7일 작업"},
        "why": "연속 시공",
    })
    if not o["applied"]:
        _decide(client, admin, o["approval_id"])
    v = _view(client, admin, sid_late)
    assert v["version"] == 3 and v["plan_finish"] == v["finish"] and _status(v) == {"A": "on_plan", "B": "on_plan"}


def test_restoring_brings_that_versions_plan(client, admin, sid_late):
    _later(client, admin, sid_late)  # 버전 2: Plan 은 버전 1 것(SNAPPED)
    client.patch(f"/api/schedules/{sid_late}/activities/B", json={"od": 4, "base_version": 2}, headers=admin)  # 버전 3
    r = client.post(f"/api/schedules/{sid_late}/versions/2/restore", json={"base_version": 3}, headers=admin)
    assert r.status_code == 200, r.json()
    v = r.json()
    assert v["version"] == 4 and _plan(v) == SNAPPED and _status(v) == {"A": "late +2", "B": "late +2"}


# ── 옛 버전·누락 ──────────────────────────────────────────────────────


def test_an_old_version_without_a_frozen_plan_computes_it_without_actuals(client, admin, session, sid_late):
    session.get(ScheduleVersion, (sid_late, 1)).plan_json = None  # 16e 전에 저장된 버전
    session.commit()
    v = _view(client, admin, sid_late)
    assert _plan(v) == [("A", "2027-03-01", "2027-03-05"), ("B", "2027-03-08", "2027-03-12")]
    assert _status(v) == {"A": "late +3", "B": "late +3"}
    v = client.patch(f"/api/schedules/{sid_late}", json={"data_date": "2027-03-04", "base_version": 1}, headers=admin).json()
    assert v["version"] == 2 and v["plan_finish"] == "2027-03-12"  # 물려받은 것도 없으므로 예전 방식 그대로


def test_a_new_version_must_say_whether_it_changes_the_plan(session, sid_late):
    schedule, conditions, _ = load(session, sid_late)
    with pytest.raises(TypeError, match="plan_change"):
        save_new_version(session, sid_late, schedule, conditions, by_kind="user", by_name="김하늘", note="",
                         changes=[], base_version=1)


# ── 사무동 시연 흐름 (Task 42 리뷰 I3) ───────────────────────────────────


async def test_office_flow_delay_then_recovery_then_late_actual(client, admin, session, monkeypatch):
    monkeypatch.setenv(fake.ENV, "1")
    add_connection(session)
    sid = office_building(session)
    session.commit()
    before = _view(client, admin, sid)
    assert (before["version"], before["plan_finish"], before["finish"]) == (2, "2027-10-20", "2027-10-29")

    await _tool(session, sid, "delay.record", {"activity_id": "A1210", "days": 3, "cause": "비 때문에"})
    v = _view(client, admin, sid)
    assert (v["version"], v["plan_finish"]) == (2, "2027-10-20")  # 지연 기록은 Plan 을 옮기지 않는다
    assert _status(v)["A1210"].startswith("late +")
    delays = client.get(f"/api/schedules/{sid}/delays", headers=admin).json()["finish"]
    assert (delays["plan"], delays["current"], delays["with_open"]) == ("2027-10-20", "2027-10-29", "2027-11-02")

    made = await _tool(session, sid, "shorten.make", {})
    best = next(o for o in made["options"] if o["recommended"])
    sent = client.post(f"/api/schedules/{sid}/scenarios/{best['scenario_id']}/submit", json={}, headers=admin).json()
    _decide(client, admin, sent["approval_id"])

    v = _view(client, admin, sid)
    assert v["version"] == 3 and v["plan_finish"] == v["finish"] == best["finish"] == "2027-10-01"
    assert {s for s in _status(v).values()} <= {"done", "on_plan"} and v["summary"]["warning_count"] == 0
    variance = client.get(f"/api/schedules/{sid}/progress", headers=admin).json()["cpm"]["finish_variance"]
    assert variance == {"days": 0, "plan": "2027-10-01", "current": "2027-10-01"}

    # 그 뒤 실적이 늦게 들어오면 다시 늦음: 진행 중인 A1090(6일, 4/17 에 절반, Plan 4/13~4/20)이 5/1 에도 60%
    await _tool(session, sid, "schedule.record_actual", {"activity_id": "A1090", "progress": 0.6, "data_date": "2027-05-01"})
    v = _view(client, admin, sid)
    assert (v["version"], v["plan_finish"], v["finish"]) == (4, "2027-10-01", "2027-10-12")
    assert _status(v)["A1090"].startswith("late +") and _status(v)["A1210"] == "late +6"
    variance = client.get(f"/api/schedules/{sid}/progress", headers=admin).json()["cpm"]["finish_variance"]
    assert variance == {"days": 6, "plan": "2027-10-01", "current": "2027-10-12"}


# ── 승인 건 summary.plan_change: 반영할 때와 같은 규칙(store.approvals.is_plan_change)을 낼 때 미리 적는다 ──────


def _pending_summary(client, admin, approval_id: int) -> dict:
    d = client.get(f"/api/approvals/{approval_id}", headers=admin).json()
    assert d["status"] == "pending", d
    return d["summary"]


def _copy(session, sid: int, source: str) -> int:
    before, stored, n = load(session, sid)
    after = replace(before, activities=tuple(replace(a, od=4) if a.id == "B" else a for a in before.activities))
    sc = scenarios.create(session, schedule_id=sid, base_version=n, name="만회안", source=source, schedule=after,
                          conditions=stored, created_by="김하늘")
    session.commit()
    return sc.id


@pytest.mark.parametrize(("source", "expected"), [("shorten", True), ("agent", True), ("delay", False)])
def test_a_submitted_copy_says_in_its_summary_whether_the_plan_is_set_again(client, admin, session, sid_late,
                                                                              source, expected):
    set_approval_mode(session, "all")
    session.commit()
    sc = _copy(session, sid_late, source)
    sent = client.post(f"/api/schedules/{sid_late}/scenarios/{sc}/submit", json={}, headers=admin).json()
    assert _pending_summary(client, admin, sent["approval_id"])["plan_change"] is expected


@pytest.mark.parametrize(("condition", "expected"), [
    ({"kind": "text_only", "params": {}, "text": "타설 전날 알림"}, False),
    ({"kind": "calendar", "params": {"days_per_week": 7, "holidays": []}, "text": "주 7일 작업"}, True),
])
async def test_a_schedule_rule_says_in_its_summary_whether_the_plan_is_set_again(client, admin, session, sid_late,
                                                                                   condition, expected):
    set_approval_mode(session, "all")
    session.commit()
    o = await _tool(session, sid_late, "rules.propose", {"scope": "schedule", "condition": condition, "why": "늘 그렇게"})
    assert _pending_summary(client, admin, o["approval_id"])["plan_change"] is expected


def test_a_condition_commit_says_the_plan_is_set_again(client, admin, session, sid_late):
    set_approval_mode(session, "all")
    session.commit()
    body = {"base_version": 1, "changes": [{"id": "in.finish_by", "params": {"date": "2027-05-31"}}]}
    r = client.post(f"/api/schedules/{sid_late}/conditions/commit", json=body, headers=admin).json()
    assert _pending_summary(client, admin, r["approval_id"])["plan_change"] is True
