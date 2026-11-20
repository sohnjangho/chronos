"""내 규칙 API(/api/rules) · 조건 창에서 내 규칙을 일정에 넣기 · 승인함의 규칙 건."""

import pytest

from app.store import approvals, my_rules
from app.store.schedules import load
from app.store.tables import MyRule
from tests import schedules

TEXT = "층당 골조 10일 넘지 않기"


def mine(cid: str = "mine.a1b2c3", text: str = TEXT, days: int = 10) -> dict:
    return {"id": cid, "layer": "mine", "kind": "max_duration", "params": {"days": days}, "text": text,
            "source": "내 규칙", "enabled": True, "overridden_by": None, "checkable": True}


def save_rule(session, *, scope="domain", domain="construction", schedule_id=None, cond=None, by="관리자") -> int:
    row = my_rules.create(session, scope=scope, domain=domain, schedule_id=schedule_id, condition_json=cond or mine(),
                          approval_id=7, created_by=by)
    session.commit()
    return row.id


def rule_row(session) -> int:
    rule = {"scope": "domain", "domain": "construction", "text": TEXT, "kind": "max_duration", "params": {"days": 10}}
    row = approvals.create(
        session, kind="rule", title=f"내 규칙 저장 — {TEXT}", reasons_json=["rule_save"], schedule_id=None,
        draft_id=None, base_version=0, summary_json={"rule": rule}, diff_json=[], snapshot_json={}, conditions_json=[],
        changes_json=[], status="pending", request="", chat_session_id=None, requested_by="관리자", link_kind="rule",
        rule_json={"scope": "domain", "domain": "construction", "schedule_id": None, "condition": mine()},
    )
    session.commit()
    return row.id


# ── 목록 ────────────────────────────────────────────────────────────


def test_list_shape(client, admin, session):
    rid = save_rule(session)
    body = client.get("/api/rules", headers=admin).json()
    assert len(body) == 1 and body[0]["created_at"].endswith("Z")
    assert {k: v for k, v in body[0].items() if k != "created_at"} == {
        "id": rid, "scope": "domain", "domain": "construction", "schedule_id": None, "condition": mine(),
        "enabled": True, "created_by": "관리자", "in_schedule": None}


def test_schedule_list_has_its_domain_and_its_own_rules(client, admin, session, sid):
    other = schedules.store(session, schedules.sample())
    a = save_rule(session)
    b = save_rule(session, scope="schedule", schedule_id=sid, cond=mine("mine.000002", "이 일정만"))
    save_rule(session, scope="schedule", schedule_id=other, cond=mine("mine.000003", "다른 일정"))
    save_rule(session, domain="production", cond=mine("mine.000004", "다른 분야"))
    body = client.get(f"/api/rules?schedule_id={sid}", headers=admin).json()
    assert [(r["id"], r["in_schedule"]) for r in body] == [(a, False), (b, False)]
    assert [r["condition"]["text"] for r in client.get("/api/rules?domain=production", headers=admin).json()] == ["다른 분야"]
    assert len(client.get("/api/rules", headers=admin).json()) == 4


def test_in_schedule_is_true_when_the_schedule_has_that_condition(client, admin, session):
    sid = schedules.store(session, schedules.sample(), [mine()])
    save_rule(session)
    assert client.get(f"/api/rules?schedule_id={sid}", headers=admin).json()[0]["in_schedule"] is True


def test_list_errors(client, admin):
    assert client.get("/api/rules?schedule_id=999", headers=admin).json()["code"] == "not_found"
    assert client.get("/api/rules").status_code == 401


# ── 켜고 끄기·지우기 ────────────────────────────────────────────────


def test_turning_off_keeps_the_schedule_copy(client, admin, session):
    sid = schedules.store(session, schedules.sample(), [mine()])
    rid = save_rule(session)
    r = client.patch(f"/api/rules/{rid}", json={"enabled": False}, headers=admin)
    assert (r.status_code, r.json()["enabled"]) == (200, False)
    session.expire_all()
    assert my_rules.for_generation(session, "construction") == []
    assert load(session, sid)[1] == [mine()]  # 일정은 사본을 가진다
    assert client.patch(f"/api/rules/{rid}", json={"enabled": "아니"}, headers=admin).status_code == 422
    assert client.patch(f"/api/rules/{rid}", json={"enabled": True, "x": 1}, headers=admin).status_code == 422


def test_owner_deletes_own_rule_and_schedule_keeps_it(client, user, session):
    sid = schedules.store(session, schedules.sample(), [mine()])
    rid = save_rule(session, by="일반 사용자")
    r = client.delete(f"/api/rules/{rid}", headers=user)
    assert (r.status_code, r.json()) == (200, {"deleted": rid})
    session.expire_all()
    assert session.query(MyRule).count() == 0 and load(session, sid)[1] == [mine()]


def test_missing_rule(client, admin):
    for r in (client.delete("/api/rules/99", headers=admin), client.patch("/api/rules/99", json={"enabled": False}, headers=admin)):
        assert (r.status_code, r.json()["message"]) == (404, "규칙을 찾을 수 없습니다.")


# ── 조건 창: 내 규칙을 이 일정에 넣기 ───────────────────────────────


def conditions_post(client, admin, sid, path, changes):
    return client.post(f"/api/schedules/{sid}/conditions/{path}", json={"base_version": 1, "changes": changes},
                       headers=admin)


def test_preview_and_commit_add_a_mine_condition(client, admin, sid, session):
    r = conditions_post(client, admin, sid, "preview", [{"add": mine()}])
    assert r.status_code == 200, r.json()
    assert [c["id"] for c in r.json()["conditions"]["layers"]["mine"]] == ["mine.a1b2c3"]
    c = conditions_post(client, admin, sid, "commit", [{"add": mine()}])
    assert c.status_code == 200 and c.json()["applied"] is False
    client.post(f"/api/approvals/{c.json()['approval_id']}/decide", json={"decision": "approve", "note": ""}, headers=admin)
    layers = client.get(f"/api/schedules/{sid}/conditions", headers=admin).json()["layers"]
    assert [x["text"] for x in layers["mine"]] == [TEXT]


@pytest.mark.parametrize("cond", [
    {**mine(), "source": "프롬프트"},
    {**mine("d.x"), "layer": "domain", "source": "분야 규칙"},
])
def test_other_layers_still_cannot_be_added(client, admin, sid, cond):
    r = conditions_post(client, admin, sid, "preview", [{"add": cond}])
    assert (r.status_code, r.json()["message"]) == (422, f"입력 조건만 더할 수 있습니다: {cond['id']}")


def test_a_mine_condition_already_there_is_refused(client, admin, session):
    sid = schedules.store(session, schedules.sample(), [mine()])
    r = conditions_post(client, admin, sid, "preview", [{"add": mine()}])
    assert (r.status_code, r.json()["message"]) == (422, "같은 id 의 조건이 이미 있습니다: mine.a1b2c3")


# ── 승인함의 규칙 건 ────────────────────────────────────────────────


def test_approvals_list_and_detail_show_a_rule_row(client, admin, session):
    aid = rule_row(session)
    listed = client.get("/api/approvals?status=pending", headers=admin)
    assert listed.status_code == 200 and listed.json()["items"][0]["kind"] == "rule"
    detail = client.get(f"/api/approvals/{aid}", headers=admin)
    assert detail.status_code == 200
    assert (detail.json()["kind"], detail.json()["summary"]["rule"]["text"], detail.json()["diff"]) == ("rule", TEXT, [])


def test_approving_a_rule_row_saves_it(client, admin, session):
    aid = rule_row(session)
    r = client.post(f"/api/approvals/{aid}/decide", json={"decision": "approve", "note": ""}, headers=admin)
    assert (r.status_code, r.json()["schedule_id"], r.json()["version"]) == (200, None, None)
    session.expire_all()
    saved = session.query(MyRule).one()
    assert (saved.approval_id, saved.created_by, saved.condition_json) == (aid, "관리자", mine())


def test_admin_deletes_a_rule_someone_else_made(client, admin, user, session):
    rid = save_rule(session, by="이도윤")
    assert client.delete(f"/api/rules/{rid}", headers=user).json()["code"] == "not_owner"
    assert client.delete(f"/api/rules/{rid}", headers=admin).json() == {"deleted": rid}
