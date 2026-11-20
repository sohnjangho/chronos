"""승인함 API: 목록·상세·결정(승인·거부·거부하고 다시 짜기)·배지 수, 승인 수준 설정, 거부 뒤 대화 이어 가기."""

import pytest
from sqlalchemy import select

from app.agent import loop
from app.errors import ApiError
from app.llm.client import LlmClient
from app.store import chats
from app.store.tables import Approval, ChangeLog, ScheduleDraft, ScheduleRecord, User
from tests.approval_doubles import crane, make_draft, submit
from tests.llm_doubles import add_connection
from tests.loop_doubles import ScriptedLlm, calls, reply

CONFLICT = "그 사이 일정이 바뀌었습니다. 에이전트에게 다시 요청해 주세요."
INVALID_APPROVAL = "이 대화에서 다시 짜기로 거부한 승인 건이 아닙니다."


@pytest.fixture
def admin_user(session) -> User:
    return session.scalars(select(User).where(User.login_id == "admin")).one()


@pytest.fixture
def chat_id(session, admin_user) -> int:
    chat = chats.create_chat(session, user_id=admin_user.id)
    chats.add_message(session, chat.id, "user", {"kind": "text", "text": "B 를 늘려 줘"})
    session.commit()
    return chat.id


def change_args(sid: int, *ops: dict, title: str = "B 기간 4일", base: int = 1) -> dict:
    return {"title": title, "schedule_id": sid, "base_version": base, "changes": list(ops)}


@pytest.fixture
def pending_first(client, session, admin_user, chat_id) -> int:
    """초안 저장(첫 저장) 승인 건. 만들어질 일정은 1번."""
    did = make_draft(session, conditions=(crane(1),), chat_session_id=chat_id)
    r, _ = submit(session, admin_user, {"draft_id": did, "title": "사무동 신축"}, chat_id=chat_id)
    assert r.ok, r.error
    return r.output["approval_id"]


@pytest.fixture
def pending(client, session, admin_user, chat_id, sid) -> int:
    """sid(A 3일 → B 2일, 버전 1)의 B 를 4일로 — 준공이 바뀌어 승인을 기다린다."""
    r, _ = submit(session, admin_user, change_args(sid, {"op": "update_activity", "id": "B", "od": 4}), chat_id=chat_id)
    assert r.ok and r.output["applied"] is False, r.error
    return r.output["approval_id"]


@pytest.fixture
def auto_applied(client, session, admin_user, chat_id, sid) -> int:
    """여유 안에서 E 를 더함 — 바로 버전 2 로 저장된 자동 적용 건."""
    new = {"id": "E", "name": "외부 정리", "od": 1, "preds": [{"pred": "A"}]}
    r, _ = submit(session, admin_user, change_args(sid, {"op": "add_activity", "activity": new}, title="E 추가"),
                  chat_id=chat_id)
    assert r.ok and r.output["applied"] is True, r.error
    return r.output["approval_id"]


def decide(client, aid: int, headers, decision: str = "approve", note: str = ""):
    return client.post(f"/api/approvals/{aid}/decide", json={"decision": decision, "note": note}, headers=headers)


# ── 지시서 시험 ─────────────────────────────────────────────────────


def test_approve_first_save_becomes_plan(client, admin, pending_first):
    r = client.post(f"/api/approvals/{pending_first}/decide", json={"decision": "approve", "note": ""}, headers=admin)
    assert r.status_code == 200 and client.get("/api/schedules/1/versions", headers=admin).json()[0]["is_plan"] is True


def test_user_role_can_approve(client, user, pending):
    assert client.post(f"/api/approvals/{pending}/decide", json={"decision": "approve", "note": ""}, headers=user).status_code == 200


def test_stale_approval_conflicts_and_does_not_apply(client, admin, pending, sid):          # Review Focus 4
    client.patch(f"/api/schedules/{sid}/activities/A", json={"od": 9, "base_version": 1}, headers=admin)
    r = client.post(f"/api/approvals/{pending}/decide", json={"decision": "approve", "note": ""}, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "version_conflict" and client.get(f"/api/schedules/{sid}", headers=admin).json()["version"] == 2


def test_reject_keeps_schedule_and_stores_note(client, admin, pending, session):
    client.post(f"/api/approvals/{pending}/decide", json={"decision": "reject", "note": "크레인 추가는 안 됨"}, headers=admin)
    assert session.get(Approval, pending).note == "크레인 추가는 안 됨"


# ── R1: 첫 저장 승인 ────────────────────────────────────────────────


def test_approving_a_first_save_creates_the_schedule_from_the_draft(client, admin, pending_first, chat_id, session):
    r = decide(client, pending_first, admin)
    assert r.json() == {"status": "approved", "version": 1, "schedule_id": 1, "chat_session_id": chat_id,
                        "owner_is_decider": True}
    view = client.get("/api/schedules/1", headers=admin).json()
    assert (view["name"], view["domain"], view["level"], view["finish"]) == ("사무동 신축", "construction", "L3", "2027-03-10")
    v1 = client.get("/api/schedules/1/versions", headers=admin).json()[0]
    assert (v1["n"], v1["by_kind"], v1["by_name"], v1["note"], v1["is_plan"]) == (1, "agent", "관리자", "사무동 신축", True)
    log = session.scalars(select(ChangeLog).where(ChangeLog.schedule_id == 1)).one()
    assert (log.version_n, log.by_kind, log.by_name, log.summary) == (1, "agent", "관리자", "사무동 신축")
    row = session.get(Approval, pending_first)
    draft = session.get(ScheduleDraft, row.draft_id)
    assert draft.used_at is not None and draft.schedule_id == 1
    assert (row.status, row.decided_by, row.schedule_id, row.version) == ("approved", "관리자", 1, 1)
    assert row.decided_at is not None


# ── R6: 결정 ────────────────────────────────────────────────────────


def test_approving_a_change_saves_a_new_agent_version(client, admin, pending, sid, chat_id):
    r = decide(client, pending, admin, note="좋습니다")
    assert r.json() == {"status": "approved", "version": 2, "schedule_id": sid, "chat_session_id": chat_id,
                        "owner_is_decider": True}
    view = client.get(f"/api/schedules/{sid}", headers=admin).json()
    assert (view["version"], view["finish"]) == (2, "2027-03-09")
    v2 = client.get(f"/api/schedules/{sid}/versions", headers=admin).json()[0]
    assert (v2["by_kind"], v2["by_name"], v2["note"]) == ("agent", "관리자", "B 기간 4일")


def test_approving_a_change_moves_plan(client, admin, pending, sid):
    """PM 결정 11-20: Plan 은 지금 일정을 실적 없이 계산한 것 — 승인한 변경(B 4일)은 Plan 도 옮긴다."""
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["plan_finish"] == "2027-03-05"
    decide(client, pending, admin)
    view = client.get(f"/api/schedules/{sid}", headers=admin).json()
    b = next(a for a in view["activities"] if a["id"] == "B")
    assert (view["plan_finish"], b["plan_start"], b["plan_finish"], b["status"]) == (
        "2027-03-09", "2027-03-04", "2027-03-09", "on_plan")


def test_conflict_is_recorded_and_cannot_be_decided_again(client, admin, pending, sid):
    client.patch(f"/api/schedules/{sid}/activities/A", json={"od": 9, "base_version": 1}, headers=admin)
    r = decide(client, pending, admin)
    assert r.json() == {"code": "version_conflict", "message": CONFLICT, "detail": {"current": 2}}
    detail = client.get(f"/api/approvals/{pending}", headers=admin).json()
    assert (detail["status"], detail["decided_by"], detail["version"]) == ("conflict", "관리자", None)
    again = decide(client, pending, admin)
    assert again.status_code == 409 and again.json()["code"] == "already_decided"


def test_reject_does_not_touch_the_schedule(client, admin, pending, sid, chat_id):
    r = decide(client, pending, admin, "reject", "  크레인 추가는 안 됨  ")
    assert r.json() == {"status": "rejected", "version": None, "schedule_id": sid, "chat_session_id": chat_id,
                        "owner_is_decider": True}
    detail = client.get(f"/api/approvals/{pending}", headers=admin).json()
    assert (detail["status"], detail["note"], detail["retry"]) == ("rejected", "크레인 추가는 안 됨", False)
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["version"] == 1


def test_reject_retry_needs_a_note(client, admin, pending):
    r = decide(client, pending, admin, "reject_retry", "   ")
    assert r.status_code == 422
    assert r.json() == {"code": "note_required", "message": "다시 짜게 하려면 이유를 적어 주세요.", "detail": None}
    assert client.get(f"/api/approvals/{pending}", headers=admin).json()["status"] == "pending"
    r = decide(client, pending, admin, "reject_retry", "준공은 그대로 두고 다시")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    detail = client.get(f"/api/approvals/{pending}", headers=admin).json()
    assert (detail["retry"], detail["note"]) == (True, "준공은 그대로 두고 다시")


def test_already_decided_is_409(client, admin, user, pending):
    assert decide(client, pending, admin).status_code == 200
    for decision in ("approve", "reject"):
        r = decide(client, pending, user, decision, "x")
        assert r.status_code == 409
        assert r.json() == {"code": "already_decided", "message": "이미 결정된 건입니다.", "detail": None}


def test_two_people_approving_at_once_apply_it_only_once(client, admin, pending_first, session, admin_user):
    """다른 사람이 먼저 승인한 건을 낡은 세션이 다시 승인하면 409 already_decided, 일정은 하나뿐이다."""
    from app.programs.approvals import service
    from app.programs.approvals.schemas import DecideIn
    from app.store.tables import ScheduleRecord

    stale = session.get(Approval, pending_first)
    assert stale.status == "pending"  # 이 세션은 결정 전 값을 쥐고 있다
    assert decide(client, pending_first, admin).status_code == 200
    with pytest.raises(ApiError) as caught:
        service.decide(session, pending_first, DecideIn(decision="approve"), admin_user)
    assert (caught.value.status_code, caught.value.code) == (409, "already_decided")
    session.expire_all()
    assert len(session.scalars(select(ScheduleRecord)).all()) == 1
    assert session.get(Approval, pending_first).status == "approved"


@pytest.mark.parametrize(
    "body",
    [{"decision": "maybe", "note": ""}, {"decision": "approve", "note": "가" * 1001}, {"decision": "approve", "x": 1}],
    ids=["unknown_decision", "note_too_long", "unknown_field"],
)
def test_decision_body_is_checked(client, admin, pending, body):
    r = client.post(f"/api/approvals/{pending}/decide", json=body, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_unknown_approval_and_login(client, admin):
    r = decide(client, 999, admin)
    assert r.status_code == 404 and r.json()["message"] == "승인 건을 찾을 수 없습니다."
    assert client.get("/api/approvals/999", headers=admin).status_code == 404
    for path in ("/api/approvals", "/api/approvals/count", "/api/approvals/1", "/api/settings/approval"):
        assert client.get(path).status_code == 401


# ── 목록·상세·배지 ──────────────────────────────────────────────────


def test_lists_by_status_with_the_current_mode(client, admin, pending, pending_first, auto_applied):
    body = client.get("/api/approvals", headers=admin).json()  # 기본은 pending, 새것부터
    assert body["mode"] == "important"
    assert [i["id"] for i in body["items"]] == [pending_first, pending]
    item = body["items"][1]
    assert set(item) == {
        "id", "kind", "title", "status", "reasons", "schedule_id", "draft_id", "base_version", "version", "restore_to",
        "retry", "request", "chat_session_id", "requested_by", "decided_by", "note", "created_at", "decided_at",
        "summary",
    }
    assert (item["kind"], item["reasons"], item["request"], item["requested_by"]) == (
        "change", ["finish_changed"], "B 를 늘려 줘", "관리자")
    assert item["created_at"].endswith("Z") and item["summary"]["finish"]["delta_days"] == 4
    decide(client, pending, admin, "reject", "아니요")
    decided = client.get("/api/approvals?status=decided", headers=admin).json()["items"]
    assert [(i["id"], i["status"]) for i in decided] == [(pending, "rejected")]
    auto = client.get("/api/approvals?status=auto", headers=admin).json()["items"]
    assert [(i["id"], i["status"], i["version"], i["restore_to"]) for i in auto] == [(auto_applied, "auto", 2, 1)]
    assert client.get("/api/approvals?status=all", headers=admin).status_code == 422


def test_detail_has_the_diff(client, user, pending):
    detail = client.get(f"/api/approvals/{pending}", headers=user).json()  # 모든 계정이 같은 승인함을 본다
    assert detail["mode"] == "important" and detail["base_version"] == 1
    assert detail["diff"] == [
        {"activity_id": "B", "name": "작업 B", "before": {"start": "2027-03-04", "finish": "2027-03-05"},
         "after": {"start": "2027-03-04", "finish": "2027-03-09"}, "finish_delta": 4},
    ]
    assert detail["summary"]["check"] == {"passed": 4, "violations": [], "uncheckable": 0, "invalid": 0}


def test_count_of_pending_for_the_menubar_badge(client, admin, user, pending, pending_first):
    assert client.get("/api/approvals/count", headers=user).json() == {"pending": 2}
    decide(client, pending, admin)
    assert client.get("/api/approvals/count", headers=admin).json() == {"pending": 1}


def test_auto_applied_change_can_be_undone_with_restore(client, admin, auto_applied, sid):
    item = client.get(f"/api/approvals/{auto_applied}", headers=admin).json()
    r = client.post(f"/api/schedules/{sid}/versions/{item['restore_to']}/restore", json={"base_version": 2}, headers=admin)
    assert r.status_code == 200 and r.json()["version"] == 3 and [a["id"] for a in r.json()["activities"]] == ["A", "B"]


# ── R9: 승인 수준 ───────────────────────────────────────────────────


def test_approval_mode_setting(client, admin, user):
    assert client.get("/api/settings/approval", headers=user).json() == {"mode": "important"}
    r = client.put("/api/settings/approval", json={"mode": "auto"}, headers=user)
    assert r.status_code == 403 and r.json()["code"] == "admin_only"
    assert client.put("/api/settings/approval", json={"mode": "auto"}, headers=admin).json() == {"mode": "auto"}
    assert client.get("/api/settings/approval", headers=user).json() == {"mode": "auto"}
    assert client.get("/api/approvals", headers=user).json()["mode"] == "auto"
    for bad in ({"mode": "never"}, {"mode": "all", "x": 1}, {}):
        assert client.put("/api/settings/approval", json=bad, headers=admin).status_code == 422


# ── R7: 거부하고 다시 짜기 → 대화 이어 가기 ─────────────────────────


@pytest.fixture
def scripted(session, monkeypatch) -> ScriptedLlm:
    add_connection(session)
    llm = ScriptedLlm([reply("다시 짜 보겠습니다.")])
    monkeypatch.setattr(loop, "default_llm", lambda s: LlmClient(s, transport=llm.transport))
    return llm


def resume(client, chat_id: int, headers, aid: int):
    return client.post(f"/api/chat/sessions/{chat_id}/messages", json={"approval_id": aid, "ui": {}}, headers=headers)


def test_reject_retry_resumes_the_chat(client, admin, pending, chat_id, scripted):
    decide(client, pending, admin, "reject_retry", "준공은 그대로 두고 다시")
    note = "준공은 그대로 두고 다시"
    r = resume(client, chat_id, admin, pending)
    assert r.status_code == 200 and r.text.rstrip().endswith("event: done\ndata: {}")
    messages = client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["messages"]
    assert [m["role"] for m in messages] == ["user", "user", "assistant"]
    assert messages[1]["content"] == {"kind": "approval_rejected", "approval_id": pending, "title": "B 기간 4일",
                                      "note": "준공은 그대로 두고 다시"}
    model_input = scripted.last_body["messages"][-1]["content"]
    assert f"승인 요청이 거부됨 (승인 {pending}: B 기간 4일)" in model_input
    assert f"거부 이유: {note}" in model_input and "out__submit_change" in model_input


def test_dates_in_the_rejection_note_reach_the_date_helper(client, admin, pending, chat_id, scripted):
    decide(client, pending, admin, "reject_retry", "준공을 12월 15일로 맞춰서 다시")
    resume(client, chat_id, admin, pending)
    assert "- '12월 15일' → " in scripted.last_body["messages"][0]["content"]  # 날짜는 코드가 정한다


@pytest.mark.parametrize("case", ["pending", "plain_reject", "approved", "other_chat", "missing"])
def test_resume_rejects_a_wrong_approval(client, admin, pending, chat_id, scripted, case):
    other = client.post("/api/chat/sessions", json={}, headers=admin).json()["id"]
    target = chat_id
    if case == "plain_reject":
        decide(client, pending, admin, "reject", "아니요")
    elif case == "approved":
        decide(client, pending, admin)
    elif case == "other_chat":
        decide(client, pending, admin, "reject_retry", "다시")
        target = other
    r = resume(client, target, admin, 999 if case == "missing" else pending)
    assert r.status_code == 422 and r.json() == {"code": "invalid_approval", "message": INVALID_APPROVAL, "detail": None}
    assert len(client.get(f"/api/chat/sessions/{target}", headers=admin).json()["messages"]) == (1 if target == chat_id else 0)


def test_resume_with_the_same_approval_twice_is_422(client, admin, pending, chat_id, scripted):
    decide(client, pending, admin, "reject_retry", "다시")
    assert resume(client, chat_id, admin, pending).status_code == 200
    r = resume(client, chat_id, admin, pending)
    assert r.status_code == 422 and r.json()["message"] == "이미 이어서 처리한 승인 건입니다."


def test_message_takes_exactly_one_input(client, admin, chat_id):
    r = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"text": "안녕", "approval_id": 1}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_agent_turn_submits_a_draft_and_the_approval_card_is_kept(client, admin, chat_id, scripted, session):
    did = make_draft(session, chat_session_id=chat_id)
    scripted._script.clear()
    scripted.push(calls("out.submit_change", {"draft_id": did, "title": "사무동 신축"}),
                  reply("승인함에서 승인을 기다립니다."))
    r = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"text": "저장해 줘", "ui": {}}, headers=admin)
    assert "event: approval\n" in r.text
    messages = client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["messages"]
    event = next(m for m in messages if m["role"] == "event")
    aid = event["content"]["data"]["id"]
    assert event["content"]["type"] == "approval" and set(event["content"]["data"]) == {"id", "title", "reasons", "summary"}
    item = client.get(f"/api/approvals/{aid}", headers=admin).json()
    assert (item["status"], item["request"], item["chat_session_id"]) == ("pending", "저장해 줘", chat_id)


# ══ Fix round 1 ════════════════════════════════════════════════════


def test_retry_decided_by_someone_else_waits_for_the_chat_owner(client, admin, user, pending, chat_id, scripted):
    """I2: 대화 주인이 아닌 사람이 다시 짜게 하면, 주인의 대화에 '다시 짜기 요청' 으로 남고 주인만 이어 간다."""
    r = decide(client, pending, user, "reject_retry", "준공은 그대로 두고 다시")
    assert r.json()["owner_is_decider"] is False and r.json()["chat_session_id"] == chat_id
    listed = {s["id"]: s for s in client.get("/api/chat/sessions", headers=admin).json()}
    assert listed[chat_id]["pending_retries"] == 1
    detail = client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()
    [retry] = detail["pending_retries"]
    assert set(retry) == {"approval_id", "title", "note", "decided_by_name", "decided_at"}
    assert (retry["approval_id"], retry["title"], retry["note"], retry["decided_by_name"]) == (
        pending, "B 기간 4일", "준공은 그대로 두고 다시", "일반 사용자")
    assert retry["decided_at"].endswith("Z")
    assert resume(client, chat_id, user, pending).status_code == 404  # 남의 대화로는 턴을 돌리지 않는다
    assert resume(client, chat_id, admin, pending).status_code == 200
    assert client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["pending_retries"] == []
    assert client.get("/api/chat/sessions", headers=admin).json()[0]["pending_retries"] == 0


def test_only_retry_rejections_are_pending_retries(client, admin, pending, pending_first, chat_id):
    decide(client, pending, admin, "reject", "아니요")
    r = decide(client, pending_first, admin, "reject_retry", "다시")
    assert r.json()["owner_is_decider"] is True  # 주인이 결정했으면 화면이 바로 이어 간다
    retries = client.get(f"/api/chat/sessions/{chat_id}", headers=admin).json()["pending_retries"]
    assert [x["approval_id"] for x in retries] == [pending_first]


def test_a_new_chat_has_no_pending_retries(client, admin):
    created = client.post("/api/chat/sessions", json={}, headers=admin).json()
    assert set(created) == {"id", "title", "schedule_id", "created_at"}
    assert client.get("/api/chat/sessions", headers=admin).json()[0]["pending_retries"] == 0
    assert client.get(f"/api/chat/sessions/{created['id']}", headers=admin).json()["pending_retries"] == []


def test_approving_a_first_save_whose_draft_was_used_meanwhile(client, admin, pending_first, session):
    """m1: 그 사이 초안이 쓰였으면 반영하지 않고 409 draft_used, status conflict."""
    row = session.get(Approval, pending_first)
    session.get(ScheduleDraft, row.draft_id).used_at = row.created_at
    session.commit()
    r = decide(client, pending_first, admin)
    assert r.status_code == 409
    assert r.json() == {"code": "draft_used", "message": "이미 저장한 초안입니다.", "detail": None}
    assert client.get(f"/api/approvals/{pending_first}", headers=admin).json()["status"] == "conflict"
    session.expire_all()
    assert session.scalars(select(ScheduleRecord)).all() == []
