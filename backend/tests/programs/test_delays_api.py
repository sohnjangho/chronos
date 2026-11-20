"""지연 기록 API: 기록·고침·지우기·분석·지연 반영안·미리 보기. 기록한 지연은 일정(Plan 포함)을 바꾸지 않는다."""

from dataclasses import replace

import pytest

from app.core.model import Relation, Resource
from app.store.delays import DelayEventRow
from app.store.schedules import load
from app.store.versions import save_new_version
from tests.approval_doubles import finish_by
from tests.schedules import make, store, task

B2 = {"activity_id": "B", "start_date": "2027-03-04", "days": 2, "cause": "우천", "responsibility": "force"}


@pytest.fixture
def sid3(session) -> int:
    """A 3일 → B 2일, A → C 1일. A 3/1~3/3, B 3/4~3/5, C 3/4. 준공 3/5."""
    return store(session, make([task("A", 3), task("B", 2), task("C", 1)], [Relation("A", "B"), Relation("A", "C")]))


def url(sid: int, rest: str = "") -> str:
    return f"/api/schedules/{sid}/delays{rest}"


def post_raw(client, admin, sid: int, body: dict):
    return client.post(url(sid), json=body, headers=admin)


def post(client, admin, sid: int, body: dict) -> dict:
    r = post_raw(client, admin, sid, body)
    assert r.status_code == 200, r.json()
    return r.json()


def get(client, admin, sid: int) -> dict:
    r = client.get(url(sid), headers=admin)
    assert r.status_code == 200, r.json()
    return r.json()


def patch(client, admin, sid: int, eid: int, body: dict):
    return client.patch(url(sid, f"/{eid}"), json=body, headers=admin)


def view(client, admin, sid: int) -> dict:
    return client.get(f"/api/schedules/{sid}", headers=admin).json()


def submit(client, admin, sid: int, sc: int) -> int:
    r = client.post(f"/api/schedules/{sid}/scenarios/{sc}/submit", json={}, headers=admin)
    assert r.status_code == 200, r.json()
    return r.json()["approval_id"]


def approve(client, admin, aid: int) -> None:
    r = client.post(f"/api/approvals/{aid}/decide", json={"decision": "approve", "note": ""}, headers=admin)
    assert r.status_code == 200, r.json()


def scenario(client, admin, sid: int, body: dict | None = None):
    return client.post(url(sid, "/scenario"), json=body or {}, headers=admin)


@pytest.fixture
def reflected_event(client, admin, sid3) -> int:
    """B +2 를 지연 반영안으로 승인해 버전 2 에 반영한 사건."""
    eid = post(client, admin, sid3, B2)["events"][0]["id"]
    approve(client, admin, submit(client, admin, sid3, scenario(client, admin, sid3).json()["scenario_id"]))
    return eid


# ── 지시서 시험 ─────────────────────────────────────────────────────


def test_record_and_analyze_on_critical(client, admin, sid3):
    r = post(client, admin, sid3, B2)
    i = r["events"][0]["impact"]
    assert (i["finish_delta"], i["absorbed"], r["finish"]["with_open"], r["totals"]["by_responsibility"]["force"]) == (
        2, 0, "2027-03-09", 2)


def test_float_absorbs_noncritical(client, admin, sid3):
    r = post(client, admin, sid3, {"activity_id": "C", "start_date": "2027-03-04", "days": 1, "cause": "자재 늦음",
                                   "responsibility": "owner"})
    e = r["events"][0]
    assert (e["impact"]["absorbed"], e["impact"]["critical_added"], r["totals"]["absorbed_events"]) == (
        1, [{"id": "C", "name": "작업 C"}], 1)


def test_each_event_gets_its_share_in_start_order(client, admin, sid3):
    post(client, admin, sid3, {**B2, "start_date": "2027-03-03"})
    r = post(client, admin, sid3, {"activity_id": "C", "start_date": "2027-03-02", "days": 1, "cause": "자재 늦음",
                                   "responsibility": "owner"})
    assert [(e["activity_id"], e["impact"]["finish_delta"]) for e in r["events"]] == [("C", 0), ("B", 2)]


def test_cost_is_finish_delta_times_daily_cost(client, admin, sid3):
    r = post(client, admin, sid3, {**B2, "daily_cost": 3_100_000})
    assert r["events"][0]["impact"]["cost"] == 6_200_000 and r["totals"]["cost"] == 6_200_000


def test_reflected_event_is_not_inserted_again(client, admin, session, sid3):                      # Review Focus 1
    post(client, admin, sid3, B2)
    sc = scenario(client, admin, sid3).json()["scenario_id"]
    approve(client, admin, submit(client, admin, sid3, sc))
    r = get(client, admin, sid3)
    e = r["events"][0]
    assert (e["status"], e["impact"]["finish_delta"], r["finish"]["current"], r["finish"]["with_open"]) == (
        "reflected", 2, "2027-03-09", "2027-03-09")
    r2 = post(client, admin, sid3, {**B2, "days": 1})
    assert r2["events"][-1]["impact"]["finish_delta"] == 1 and r2["finish"]["with_open"] == "2027-03-10"


def test_reflected_event_is_locked(client, admin, sid3, reflected_event):
    r = patch(client, admin, sid3, reflected_event, {"days": 5})
    assert r.status_code == 409 and r.json() == {
        "code": "delay_reflected", "message": "일정에 반영된 사건은 일수·대상·시작일을 바꿀 수 없습니다.", "detail": None}


def test_unknown_activity_is_422(client, admin, sid3):
    assert post_raw(client, admin, sid3, {**B2, "activity_id": "Z"}).json() == {
        "code": "invalid_delay", "message": "없는 액티비티입니다: Z", "detail": None}


def test_scenario_from_open_delays(client, admin, sid3):
    e1 = post(client, admin, sid3, B2)["events"][0]["id"]
    r = post(client, admin, sid3, {**B2, "activity_id": "C", "start_date": "2027-03-05", "days": 3})
    e2 = r["events"][-1]["id"]
    sc = scenario(client, admin, sid3)
    assert sc.status_code == 200, sc.json()
    s = client.get(f"/api/schedules/{sid3}/scenarios/{sc.json()['scenario_id']}", headers=admin).json()
    assert (s["delay_event_ids"], s["summary"]["finish"], s["source"], s["name"]) == (
        [e1, e2], r["finish"]["with_open"], "delay", "지연 반영안 (2건)")


def test_no_open_delays_scenario_is_422(client, admin, sid3):
    r = scenario(client, admin, sid3)
    assert r.status_code == 422 and r.json()["code"] == "no_open_delays"
    assert r.json()["message"] == "열린 지연 사건이 없습니다."


def test_preview_shows_open_delays_without_saving(client, admin, sid3):
    post(client, admin, sid3, B2)
    p = client.get(url(sid3, "/preview"), headers=admin).json()
    assert p["view"]["finish"] == "2027-03-09" and [m["activity_id"] for m in p["moved"]] == ["B"]
    assert view(client, admin, sid3)["version"] == 1


# ── PM 결정: 기록한 지연은 Plan 을 옮기지 않는다 ──────────────────────────


def test_recorded_delays_never_move_plan(client, admin, sid3, reflected_event):
    r = get(client, admin, sid3)
    assert (r["finish"]["plan"], r["finish"]["current"]) == ("2027-03-05", "2027-03-09")
    v = view(client, admin, sid3)
    b = next(a for a in v["activities"] if a["id"] == "B")
    assert (v["plan_finish"], b["plan_finish"], b["status"]) == ("2027-03-05", "2027-03-05", "late +2")


def test_preview_shows_open_delay_as_late_against_an_unmoved_plan(client, admin, sid3):
    post(client, admin, sid3, B2)
    b = next(a for a in client.get(url(sid3, "/preview"), headers=admin).json()["view"]["activities"]
             if a["id"] == "B")
    assert (b["plan_start"], b["plan_finish"], b["es"], b["ef"], b["status"]) == (
        "2027-03-04", "2027-03-05", "2027-03-08", "2027-03-09", "late +2")
    m = client.get(url(sid3, "/preview"), headers=admin).json()["moved"][0]
    assert m == {"activity_id": "B", "name": "작업 B", "before": {"start": "2027-03-04", "finish": "2027-03-05"},
                 "after": {"start": "2027-03-08", "finish": "2027-03-09"}}


# ── 모양·합계 ─────────────────────────────────────────────────────────


def test_full_shape_of_an_open_event(client, admin, sid3):
    r = post(client, admin, sid3, {**B2, "daily_cost": 1000, "evidence": "작업 일지 3/4"})
    e = r["events"][0]
    assert set(e) == {"id", "activity_id", "activity_name", "start_date", "days", "cause", "responsibility",
                      "daily_cost", "evidence", "source", "status", "impact", "analyzed_version",
                      "reflected_version", "stale", "created_by", "created_at"}
    assert (e["activity_name"], e["source"], e["status"], e["analyzed_version"], e["reflected_version"], e["stale"],
            e["created_by"], e["evidence"]) == ("작업 B", "user", "open", 1, None, False, "관리자", "작업 일지 3/4")
    assert e["created_at"].endswith("Z")
    assert e["impact"] == {"applied": True, "note": None, "finish_before": "2027-03-05", "finish_after": "2027-03-09",
                           "finish_delta": 2, "absorbed": 0, "milestones": [], "critical_added": [],
                           "critical_removed": [{"id": "A", "name": "작업 A"}], "affected": ["B"], "new_clashes": [], "cost": 2000}
    assert r["totals"] == {"finish_impact": 2, "by_responsibility": {"owner": 0, "ours": 0, "force": 2, "undecided": 0},
                           "absorbed": 0, "absorbed_events": 0, "cost": 2000, "open_count": 1}
    assert (r["schedule_id"], r["version"]) == (sid3, 1)
    assert r["finish"] == {"plan": "2027-03-05", "current": "2027-03-05", "with_open": "2027-03-09",
                           "deadline": None, "deadline_float": None}


def test_no_events(client, admin, sid3):
    r = get(client, admin, sid3)
    assert (r["events"], r["totals"]["cost"], r["totals"]["open_count"], r["finish"]["with_open"]) == (
        [], None, 0, "2027-03-05")


def test_deadline_float_counts_workdays_from_with_open(client, admin, session, sid3):
    schedule, _, _ = load(session, sid3)
    save_new_version(session, sid3, schedule, [finish_by("2027-03-12")], by_kind="user", by_name="관리자", note="기한",
                     changes=[], base_version=1)
    r = post(client, admin, sid3, B2)
    assert (r["finish"]["deadline"], r["finish"]["deadline_float"]) == ("2027-03-12", 3)


def test_milestone_event_is_recorded_but_not_applied(client, admin, session):
    sid = store(session, make([task("A", 3), task("M", 0, kind="finish_ms")], [Relation("A", "M")]))
    i = post(client, admin, sid, {**B2, "activity_id": "M", "daily_cost": 10})["events"][0]["impact"]
    assert (i["applied"], i["note"], i["finish_delta"], i["absorbed"], i["cost"]) == (
        False, "마일스톤에는 기간을 더할 수 없습니다. 앞 작업에 기록해 주세요.", 0, 0, 0)


def test_milestone_shift_and_clash_carry_names(client, admin, session):
    """A(크레인) → M, X 3일 → E(크레인). A 를 하루 미루면 A 가 3/2~3/4 로 E(3/4~3/5) 와 겹치고 M 이 밀린다."""
    s = make([task("A", 3, resources=("crane",)), task("M", 0, kind="finish_ms"), task("X", 3),
              task("E", 2, resources=("crane",))],
             [Relation("A", "M"), Relation("X", "E")], [Resource("crane", "타워크레인", "대", 1)])
    sid = store(session, s)
    i = post(client, admin, sid, {**B2, "activity_id": "A", "start_date": "2027-03-01", "days": 1})["events"][0]["impact"]
    assert [m["name"] for m in i["milestones"]] == ["작업 M"]
    assert [(c["resource_id"], c["name"], c["first"]) for c in i["new_clashes"]] == [("crane", "타워크레인", "2027-03-04")]


# ── 고침·지우기·분석 ───────────────────────────────────────────────────


def test_patch_open_event_reanalyses(client, admin, sid3):
    eid = post(client, admin, sid3, B2)["events"][0]["id"]
    r = patch(client, admin, sid3, eid, {"days": 1, "cause": "우천(정정)"})
    assert r.status_code == 200, r.json()
    e = r.json()["events"][0]
    assert (e["days"], e["cause"], e["impact"]["finish_delta"], r.json()["finish"]["with_open"]) == (
        1, "우천(정정)", 1, "2027-03-08")


def test_patch_rejects_null_and_unknown_activity(client, admin, sid3):
    eid = post(client, admin, sid3, B2)["events"][0]["id"]
    assert patch(client, admin, sid3, eid, {"days": None}).status_code == 422
    assert patch(client, admin, sid3, eid, {"activity_id": "Z"}).json()["code"] == "invalid_delay"
    assert patch(client, admin, sid3, eid, {"daily_cost": None}).status_code == 200


def test_reflected_event_allows_cause_and_cost_and_recosts(client, admin, sid3, reflected_event):
    r = patch(client, admin, sid3, reflected_event, {"responsibility": "owner", "daily_cost": 500})
    assert r.status_code == 200, r.json()
    e = r.json()["events"][0]
    assert (e["responsibility"], e["impact"]["cost"], e["impact"]["finish_delta"]) == ("owner", 1000, 2)
    for body in ({"activity_id": "C"}, {"start_date": "2027-03-05"}):
        assert patch(client, admin, sid3, reflected_event, body).json()["code"] == "delay_reflected"


def test_delete(client, admin, session, sid3, reflected_event):
    r = client.delete(url(sid3, f"/{reflected_event}"), headers=admin)
    assert r.status_code == 409 and r.json()["message"] == "일정에 반영된 사건은 지울 수 없습니다."
    eid = post(client, admin, sid3, {**B2, "days": 1})["events"][-1]["id"]
    r = client.delete(url(sid3, f"/{eid}"), headers=admin)
    assert r.status_code == 200 and [e["id"] for e in r.json()["events"]] == [reflected_event]
    assert session.get(DelayEventRow, eid) is None


def test_get_reanalyses_open_events_after_a_new_version(client, admin, session, sid3):
    post(client, admin, sid3, B2)
    schedule, conditions, _ = load(session, sid3)
    longer = replace(schedule, activities=tuple(replace(a, od=5) if a.id == "C" else a for a in schedule.activities))
    save_new_version(session, sid3, longer, conditions, by_kind="user", by_name="관리자", note="C 5일", changes=[],
                     base_version=1)
    r = get(client, admin, sid3)
    e = r["events"][0]
    # C 5일(3/4~3/10)이 준공을 잡아 B +2(3/9 끝)는 모두 흡수된다
    assert (r["version"], e["analyzed_version"], e["impact"]["finish_delta"], e["impact"]["absorbed"],
            r["finish"]["with_open"]) == (2, 2, 0, 2, "2027-03-10")
    assert session.get(DelayEventRow, e["id"]).analyzed_version == 2


def test_analyze_endpoint(client, admin, sid3):
    post(client, admin, sid3, B2)
    r = client.post(url(sid3, "/analyze"), headers=admin)
    assert r.status_code == 200 and r.json()["events"][0]["impact"]["finish_delta"] == 2


def test_scenario_with_chosen_events(client, admin, sid3):
    post(client, admin, sid3, B2)
    e2 = post(client, admin, sid3, {**B2, "activity_id": "C", "days": 1})["events"][-1]["id"]
    sc = scenario(client, admin, sid3, {"event_ids": [e2]}).json()["scenario_id"]
    s = client.get(f"/api/schedules/{sid3}/scenarios/{sc}", headers=admin).json()
    assert (s["delay_event_ids"], s["name"]) == ([e2], "지연 반영안 (1건)")


@pytest.mark.parametrize("body", [
    {**B2, "days": 0}, {**B2, "days": 366}, {**B2, "cause": ""}, {**B2, "cause": "가" * 201},
    {**B2, "daily_cost": -1}, {**B2, "evidence": "가" * 201}, {**B2, "responsibility": "them"}, {**B2, "x": 1},
    {k: v for k, v in B2.items() if k != "cause"},
])
def test_bad_body_is_422(client, admin, sid3, body):
    assert post_raw(client, admin, sid3, body).json()["code"] == "invalid_request"


def test_not_found_and_auth(client, admin, user, session, sid3):
    assert client.get(url(999), headers=admin).status_code == 404
    assert patch(client, admin, sid3, 999, {"days": 1}).status_code == 404
    assert client.delete(url(sid3, "/999"), headers=admin).status_code == 404
    other = store(session, make([task("A", 3), task("B", 2)], [Relation("A", "B")]))
    eid = post(client, admin, sid3, B2)["events"][0]["id"]
    assert patch(client, admin, other, eid, {"days": 1}).status_code == 404  # 다른 일정의 사건
    assert client.get(url(sid3)).status_code == 401
    assert client.get(url(sid3), headers=user).status_code == 200


def test_with_open_ignores_a_later_reflected_event(client, admin, sid3, reflected_event):
    """반영된 B +2(3/4, 준공 3/9 로 적힘)보다 앞선 날의 열린 B +1(3/2) → 열린 것만 넣은 준공 3/10."""
    r = post(client, admin, sid3, {**B2, "start_date": "2027-03-02", "days": 1})
    assert (r["finish"]["current"], r["finish"]["with_open"]) == ("2027-03-09", "2027-03-10")


def test_deleting_an_event_reshares_the_rest(client, admin, sid3):
    """C +2(3/2) 가 준공을 3/8 로 하루 민 뒤 B +2(3/3) 의 몫은 1. C 사건을 지우면 B 의 몫은 2."""
    c = post(client, admin, sid3, {**B2, "activity_id": "C", "start_date": "2027-03-02"})["events"][0]["id"]
    r = post(client, admin, sid3, {**B2, "start_date": "2027-03-03"})
    assert [e["impact"]["finish_delta"] for e in r["events"]] == [1, 1]
    r = client.delete(url(sid3, f"/{c}"), headers=admin).json()
    assert [(e["activity_id"], e["impact"]["finish_delta"]) for e in r["events"]] == [("B", 2)]


# ── Fix round 1 ──────────────────────────────────────────────────────


def test_same_day_events_keep_id_order_past_nine(client, admin, session, sid3):                    # I1
    other = store(session, make([task("A", 3)]))
    for _ in range(8):  # id 1~8 을 다른 일정에 써서 sid3 의 사건이 id 9·10 이 되게 한다
        post(client, admin, other, {**B2, "activity_id": "A"})
    first = post(client, admin, sid3, {**B2, "activity_id": "C", "days": 1, "responsibility": "owner"})
    r = post(client, admin, sid3, {**B2, "activity_id": "C", "days": 1, "responsibility": "ours"})
    assert [e["id"] for e in r["events"]] == [9, 10] and first["events"][0]["id"] == 9
    # 9(발주처) 가 먼저 들어가 여유 하루에 흡수되고, 10(우리) 이 준공을 하루 민다
    assert [e["impact"]["finish_delta"] for e in r["events"]] == [0, 1]
    assert (r["totals"]["by_responsibility"]["owner"], r["totals"]["by_responsibility"]["ours"]) == (0, 1)


def scenario_status(client, admin, sid: int, sc: int) -> str:
    return client.get(f"/api/schedules/{sid}/scenarios/{sc}", headers=admin).json()["status"]


def test_editing_an_event_discards_its_open_scenario(client, admin, sid3):                        # I2
    eid = post(client, admin, sid3, B2)["events"][0]["id"]
    sc = scenario(client, admin, sid3).json()["scenario_id"]
    assert patch(client, admin, sid3, eid, {"cause": "우천(정정)"}).status_code == 200
    assert scenario_status(client, admin, sid3, sc) == "open"  # 일수·대상·시작일이 아니면 그대로
    r = patch(client, admin, sid3, eid, {"days": 5})
    assert r.status_code == 200 and r.json()["events"][0]["days"] == 5
    assert scenario_status(client, admin, sid3, sc) == "discarded"


def test_deleting_an_event_discards_its_open_scenario(client, admin, sid3):                       # I2
    eid = post(client, admin, sid3, B2)["events"][0]["id"]
    sc = scenario(client, admin, sid3).json()["scenario_id"]
    assert client.delete(url(sid3, f"/{eid}"), headers=admin).status_code == 200
    assert scenario_status(client, admin, sid3, sc) == "discarded"


SUBMITTED = {"code": "delay_in_submitted_plan",
             "message": "승인함에 올라간 안에 들어 있는 사건이라 고칠 수 없습니다. 그 안을 거부한 뒤 고쳐 주세요.",
             "detail": None}


def test_event_in_a_submitted_scenario_cannot_be_edited(client, admin, session, sid3):           # I2
    eid = post(client, admin, sid3, B2)["events"][0]["id"]
    sc = scenario(client, admin, sid3).json()["scenario_id"]
    submit(client, admin, sid3, sc)
    r = patch(client, admin, sid3, eid, {"days": 5})
    assert (r.status_code, r.json()) == (409, SUBMITTED)
    assert session.get(DelayEventRow, eid).days == 2 and scenario_status(client, admin, sid3, sc) == "submitted"
    assert patch(client, admin, sid3, eid, {"cause": "우천(정정)"}).status_code == 200


def test_event_in_a_submitted_scenario_cannot_be_deleted(client, admin, session, sid3):          # I2
    eid = post(client, admin, sid3, B2)["events"][0]["id"]
    submit(client, admin, sid3, scenario(client, admin, sid3).json()["scenario_id"])
    r = client.delete(url(sid3, f"/{eid}"), headers=admin)
    assert (r.status_code, r.json()) == (409, SUBMITTED) and session.get(DelayEventRow, eid) is not None


def test_scenario_of_only_unplaceable_events_explains_why(client, admin, session):               # Minor 1
    sid = store(session, make([task("A", 3), task("M", 0, kind="finish_ms")], [Relation("A", "M")]))
    eid = post(client, admin, sid, {**B2, "activity_id": "M"})["events"][0]["id"]
    r = scenario(client, admin, sid)
    assert (r.status_code, r.json()) == (422, {
        "code": "no_open_delays",
        "message": "일정에 넣을 수 있는 열린 지연 사건이 없습니다(끝난 작업·마일스톤 사건은 넣지 않습니다).",
        "detail": {"skipped": [eid]}})


def test_same_open_scenario_is_reused_only_when_identical(client, admin, sid3):                  # Minor 2
    e1 = post(client, admin, sid3, B2)["events"][0]["id"]
    s1 = scenario(client, admin, sid3).json()["scenario_id"]
    assert scenario(client, admin, sid3).json()["scenario_id"] == s1
    post(client, admin, sid3, {**B2, "activity_id": "C", "days": 1})
    s2 = scenario(client, admin, sid3).json()["scenario_id"]
    assert s2 != s1 and scenario(client, admin, sid3, {"event_ids": [e1]}).json()["scenario_id"] == s1
    names = {s["id"]: s["name"] for s in client.get(f"/api/schedules/{sid3}/scenarios", headers=admin).json()}
    assert (names[s1], names[s2]) == ("지연 반영안 (1건)", "지연 반영안 (2건)")
