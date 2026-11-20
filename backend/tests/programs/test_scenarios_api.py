"""만약에 복사본 API: 목록·상세·버리기·승인함으로 내기, 그리고 승인 결과가 복사본·지연 사건에 닿는 것."""

from dataclasses import replace
from datetime import date

import pytest

from app.core.model import Relation
from app.core.shorten import Move
from app.store import scenarios
from app.store.delays import DelayEventRow, delayed_base
from app.store.schedules import load
from app.store.tables import Approval, Scenario
from tests.schedules import make, store, task


def view(client, admin, sid: int) -> dict:
    return client.get(f"/api/schedules/{sid}", headers=admin).json()


def with_od(schedule, aid: str, od: int):
    return replace(schedule, activities=tuple(replace(a, od=od) if a.id == aid else a for a in schedule.activities))


def make_scenario(session, sid: int, schedule=None, conditions=None, **more) -> int:
    """지금 버전에서 떠 온 복사본(기본: B 4일 → 준공 3/9)."""
    current, stored, n = load(session, sid)
    fields = {"name": "B 4일", "source": "agent", "created_by": "김하늘", **more}
    row = scenarios.create(session, schedule_id=sid, base_version=n, schedule=schedule or with_od(current, "B", 4),
                           conditions=stored if conditions is None else conditions, **fields)
    session.commit()
    return row.id


@pytest.fixture
def scenario_id(session, sid) -> int:
    return make_scenario(session, sid)


def get(session, sc: int) -> Scenario:
    session.expire_all()
    return session.get(Scenario, sc)


def submit(client, admin, sid: int, sc: int, **body) -> int:
    r = client.post(f"/api/schedules/{sid}/scenarios/{sc}/submit", json=body, headers=admin)
    assert r.status_code == 200, r.json()
    return r.json()["approval_id"]


def approve(client, admin, aid: int):
    r = client.post(f"/api/approvals/{aid}/decide", json={"decision": "approve", "note": ""}, headers=admin)
    assert r.status_code == 200, r.json()


def add_open_delay(session, sid: int, aid: str, *, days: int) -> int:
    row = DelayEventRow(schedule_id=sid, activity_id=aid, start_date=date(2027, 3, 4), days=days, created_by="김하늘")
    session.add(row)
    session.commit()
    return row.id


def scenario_from(session, sid: int, d) -> int:
    row = scenarios.create(session, schedule_id=sid, base_version=d.version, name="지연 반영안 (1건)", source="delay",
                           schedule=d.schedule, conditions=d.conditions, delay_event_ids=d.event_ids,
                           created_by="김하늘")
    session.commit()
    return row.id


# ── 지시서 시험 ─────────────────────────────────────────────────────


def test_submit_creates_linked_approval(client, admin, session, sid, scenario_id):
    r = client.post(f"/api/schedules/{sid}/scenarios/{scenario_id}/submit", json={}, headers=admin).json()
    row = session.get(Approval, r["approval_id"])
    assert (row.link_kind, row.link_id, r["applied"]) == ("scenario", scenario_id, False)
    assert "finish_changed" in row.reasons_json
    assert (r["status"], row.title, row.requested_by, row.status) == ("submitted", "B 4일", "관리자", "pending")
    assert (get(session, scenario_id).status, get(session, scenario_id).approval_id) == ("submitted", r["approval_id"])


def test_approving_scenario_applies_and_reflects_its_delays(client, admin, session, sid):      # Review Focus 1
    e = add_open_delay(session, sid, "B", days=2)
    sc = scenario_from(session, sid, delayed_base(session, sid))
    a = submit(client, admin, sid, sc)
    approve(client, admin, a)
    session.expire_all()
    assert get(session, sc).status == "applied" and session.get(DelayEventRow, e).status == "reflected"
    assert session.get(DelayEventRow, e).reflected_version == 2 and view(client, admin, sid)["finish"] == "2027-03-09"
    assert delayed_base(session, sid).event_ids == []  # 반영된 사건은 다시 넣지 않는다


def test_reject_reopens_scenario(client, admin, session, sid, scenario_id):
    for decision, note in (("reject", ""), ("reject_retry", "준공은 그대로")):
        a = submit(client, admin, sid, scenario_id)
        r = client.post(f"/api/approvals/{a}/decide", json={"decision": decision, "note": note}, headers=admin)
        assert r.status_code == 200
        assert (get(session, scenario_id).status, get(session, scenario_id).approval_id) == ("open", a)


def test_stale_scenario_submit_is_409(client, admin, session, sid, scenario_id):               # Review Focus 2
    client.patch(f"/api/schedules/{sid}/activities/A", json={"od": 4, "base_version": 1}, headers=admin)
    r = client.post(f"/api/schedules/{sid}/scenarios/{scenario_id}/submit", json={}, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "scenario_stale" and session.query(Approval).count() == 0
    assert r.json()["message"] == "기준 일정이 바뀌었습니다. 복사본을 다시 만들어 주세요."


def test_conflict_on_approve_reopens_scenario(client, admin, session, sid, scenario_id):       # Review Focus 2
    a = submit(client, admin, sid, scenario_id)
    client.patch(f"/api/schedules/{sid}/activities/A", json={"od": 4, "base_version": 1}, headers=admin)
    assert client.post(f"/api/approvals/{a}/decide", json={"decision": "approve", "note": ""},
                       headers=admin).status_code == 409
    s = client.get(f"/api/schedules/{sid}/scenarios/{scenario_id}", headers=admin).json()
    assert (s["status"], s["stale"]) == ("open", True) and view(client, admin, sid)["version"] == 2


def test_conflict_leaves_its_delays_open(client, admin, session, sid):
    e = add_open_delay(session, sid, "B", days=2)
    a = submit(client, admin, sid, scenario_from(session, sid, delayed_base(session, sid)))
    client.patch(f"/api/schedules/{sid}/activities/A", json={"od": 4, "base_version": 1}, headers=admin)
    client.post(f"/api/approvals/{a}/decide", json={"decision": "approve", "note": ""}, headers=admin)
    session.expire_all()
    assert (session.get(DelayEventRow, e).status, session.get(DelayEventRow, e).reflected_version) == ("open", None)


def test_discard_and_locked(client, admin, session, sid, scenario_id):
    r = client.delete(f"/api/schedules/{sid}/scenarios/{scenario_id}", headers=admin)
    assert (r.status_code, r.json(), get(session, scenario_id).status) == (200, {"status": "discarded"}, "discarded")
    other = make_scenario(session, sid)
    submit(client, admin, sid, other)
    r = client.delete(f"/api/schedules/{sid}/scenarios/{other}", headers=admin)
    assert r.status_code == 409 and r.json() == {
        "code": "scenario_locked", "message": "승인을 기다리거나 반영된 복사본은 버릴 수 없습니다.", "detail": None}


def test_only_open_scenarios_can_be_submitted(client, admin, session, sid, scenario_id):
    client.delete(f"/api/schedules/{sid}/scenarios/{scenario_id}", headers=admin)
    r = client.post(f"/api/schedules/{sid}/scenarios/{scenario_id}/submit", json={}, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "scenario_locked"
    assert r.json()["message"] == "승인을 기다리거나 반영되었거나 버린 복사본은 낼 수 없습니다."


def test_submit_without_a_change_is_422(client, admin, session, sid):
    same = make_scenario(session, sid, schedule=load(session, sid)[0], name="그대로")
    r = client.post(f"/api/schedules/{sid}/scenarios/{same}/submit", json={}, headers=admin)
    assert (r.status_code, r.json()["code"], r.json()["message"]) == (422, "no_change", "바뀌는 것이 없습니다.")
    assert session.query(Approval).count() == 0 and get(session, same).status == "open"


def test_submit_body_is_checked(client, admin, sid, scenario_id):
    url = f"/api/schedules/{sid}/scenarios/{scenario_id}/submit"
    for body in ({"title": "가" * 101}, {"title": " "}, {"reset_plan": True}, {"other": 1}):  # PM 11-20: reset_plan 없음
        assert client.post(url, json=body, headers=admin).json()["code"] == "invalid_request"


def test_auto_mode_applies_at_once(client, admin, session, sid, scenario_id):
    client.put("/api/settings/approval", json={"mode": "auto"}, headers=admin)
    r = client.post(f"/api/schedules/{sid}/scenarios/{scenario_id}/submit", json={"title": "B 늘림"},
                    headers=admin).json()
    assert (r["applied"], r["status"], view(client, admin, sid)["version"]) == (True, "applied", 2)
    row = session.get(Approval, r["approval_id"])
    assert (row.status, row.title, get(session, scenario_id).status) == ("auto", "B 늘림", "applied")


@pytest.fixture
def sid_chain(session) -> int:
    """A 6 → B 4 → C 5, 준공 3/19."""
    return store(session, make([task("A", 6), task("B", 4), task("C", 5)], [Relation("A", "B"), Relation("B", "C")]))


def test_applied_shorten_scenario_reports_recovery(client, admin, session, sid_chain):  # 계획 이득 3, 지금 준공 3/16
    sid = sid_chain
    current = load(session, sid)[0]
    parallel = replace(current, relations=(Relation("A", "B", "SS", 3), Relation("B", "C")))
    move = Move("par:A>B", "parallel", ("A", "B"), "작업 A 절반 지점에서 작업 B 시작 (FS → SS+3)",
                relation=Relation("A", "B", "SS", 3))
    sc = make_scenario(session, sid, schedule=parallel, name="만회안 A · 병행 우선", source="shorten", moves=[move],
                       extra_summary={"gain": 3, "base_finish": "2027-03-19", "recommended": True})
    approve(client, admin, submit(client, admin, sid, sc))
    out = client.get(f"/api/schedules/{sid}/scenarios?status=applied", headers=admin).json()
    assert out[0]["recovery"] == {"planned_gain": 3, "achieved": 3}
    assert out[0]["moves"] == [{"id": "par:A>B", "kind": "parallel", "text": move.text}]
    assert (out[0]["summary"]["finish"], out[0]["summary"]["recommended"]) == ("2027-03-16", True)


# ── 목록·상세 ───────────────────────────────────────────────────────


def test_list_groups_and_shape(client, admin, session, sid):
    first, second, gone = (make_scenario(session, sid, name=n) for n in ("첫째", "둘째", "버림"))
    submit(client, admin, sid, second)
    client.delete(f"/api/schedules/{sid}/scenarios/{gone}", headers=admin)
    url = f"/api/schedules/{sid}/scenarios"
    assert [s["id"] for s in client.get(url, headers=admin).json()] == [second, first]
    assert client.get(url + "?status=applied", headers=admin).json() == []
    assert [s["id"] for s in client.get(url + "?status=all", headers=admin).json()] == [gone, second, first]
    s = client.get(url, headers=admin).json()[1]
    assert s == {"id": first, "schedule_id": sid, "name": "첫째", "source": "agent", "base_version": 1, "stale": False,
                 "status": "open", "approval_id": None, "moves": [], "delay_event_ids": [], "summary": s["summary"],
                 "created_by": "김하늘", "created_at": s["created_at"], "recovery": None}
    assert s["created_at"].endswith("Z") and s["summary"]["finish"] == "2027-03-09"
    assert client.get(url + "?status=bad", headers=admin).json()["code"] == "invalid_request"


def test_detail_has_the_diff_against_the_current_schedule(client, admin, sid, scenario_id):
    d = client.get(f"/api/schedules/{sid}/scenarios/{scenario_id}", headers=admin).json()
    assert (d["id"], d["stale"]) == (scenario_id, False)
    assert d["diff"] == [{"activity_id": "B", "name": "작업 B", "before": {"start": "2027-03-04", "finish": "2027-03-05"},
                          "after": {"start": "2027-03-04", "finish": "2027-03-09"}, "finish_delta": 4}]


def test_missing_things_are_404(client, admin, session, sid, scenario_id):
    other = store(session, make([task("A", 1)]))
    for url in ("/api/schedules/999/scenarios", f"/api/schedules/{sid}/scenarios/999",
                f"/api/schedules/{other}/scenarios/{scenario_id}"):
        assert client.get(url, headers=admin).status_code == 404
    r = client.post(f"/api/schedules/{other}/scenarios/{scenario_id}/submit", json={}, headers=admin)
    assert (r.status_code, r.json()["message"]) == (404, "복사본을 찾을 수 없습니다.")
    assert client.delete(f"/api/schedules/{sid}/scenarios/999", headers=admin).status_code == 404


def test_login_is_needed(client, user, sid, scenario_id):
    assert client.get(f"/api/schedules/{sid}/scenarios").status_code == 401
    assert client.get(f"/api/schedules/{sid}/scenarios", headers=user).status_code == 200
