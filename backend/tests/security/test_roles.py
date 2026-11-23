"""역할(F4): 현장 관리자(field)는 일정을 고치거나 승인·거부할 수 없다(403). 사용자(user)는 그대로 승인할 수 있다."""

import json

import pytest
from sqlalchemy import select

from app.agent.context import UiContext
from app.agent.loop import run_turn
from app.llm.client import LlmClient
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store import chats
from app.store.settings import set_approval_mode
from app.store.tables import FieldItem, QuestionnaireRecord, Scenario, User, WorkflowRun
from app.tools import registry
from app.tools.context import ToolContext
from tests.approval_doubles import finish_by
from tests.helpers import auth
from tests.llm_doubles import add_connection
from tests.loop_doubles import ScriptedLlm, calls, reply
from tests.schedules import sample, store

FIELD_ONLY = "현장 관리자는 일정을 고치거나 승인·거부할 수 없습니다."


@pytest.fixture
def field_user(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


def _approval(client, headers, session, sid) -> int:
    """현장 체크인 회신을 반영해 승인 대기 건 하나를 만든다(현장 관리자도 할 수 있는 일)."""
    client.get(f"/api/schedules/{sid}/field", headers=headers)
    item = session.scalars(select(FieldItem).where(FieldItem.kind == "checkin", FieldItem.status == "pending")).first()
    r = client.post(
        f"/api/schedules/{sid}/field/{item.id}/respond",
        json={"response_choice": "on_track", "reported_progress": 50, "reported_rd": 1, "response_note": ""},
        headers=headers,
    )
    assert r.status_code == 200, r.json()
    r = client.post(f"/api/schedules/{sid}/field/{item.id}/apply", headers=headers)
    assert r.status_code == 200, r.json()
    return next(i for i in r.json()["items"] if i["id"] == item.id)["approval_id"]


WRITES = [
    ("POST", "/api/schedules", {"name": "새 현장"}),
    ("PATCH", "/api/schedules/{sid}", {"data_date": "2027-03-02", "base_version": 1}),
    ("PATCH", "/api/schedules/{sid}/activities/A", {"name": "작업 A2", "base_version": 1}),
    ("POST", "/api/schedules/{sid}/activities", {"name": "작업 C", "kind": "task", "wbs": "1", "od": 1, "base_version": 1}),
    ("DELETE", "/api/schedules/{sid}/activities/B?base_version=1", None),
    ("PUT", "/api/schedules/{sid}/activities/B/predecessors", {"items": [], "base_version": 1}),
    ("POST", "/api/schedules/{sid}/versions/1/restore", {"base_version": 1}),
    # 리뷰 I-1: 가중치 방식·조건 확정(자동 승인이면 바로 새 버전)·복사본 상신도 막는다
    ("PUT", "/api/schedules/{sid}/weight-mode", {"mode": "manual"}),
    ("POST", "/api/schedules/{sid}/conditions/commit", {"base_version": 1, "changes": []}),
    ("POST", "/api/schedules/{sid}/scenarios/1/submit", {}),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES, ids=[f"{m} {p}" for m, p, _ in WRITES])
def test_field_role_cannot_edit_schedules(client, field_user, sid, method, path, body):
    r = client.request(method, path.format(sid=sid), json=body, headers=field_user)

    assert r.status_code == 403, r.json()
    assert (r.json()["code"], r.json()["message"]) == ("field_read_only", FIELD_ONLY)


def test_field_role_still_reads_schedules(client, field_user, sid):
    assert client.get(f"/api/schedules/{sid}", headers=field_user).status_code == 200


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_field_role_cannot_decide_approvals_but_can_raise_them(client, field_user, session, sid, decision):
    approval_id = _approval(client, field_user, session, sid)

    r = client.post(f"/api/approvals/{approval_id}/decide", json={"decision": decision}, headers=field_user)

    assert r.status_code == 403, r.json()
    assert (r.json()["code"], r.json()["message"]) == ("field_read_only", FIELD_ONLY)


def test_user_role_may_still_approve(client, user, session, sid):
    approval_id = _approval(client, user, session, sid)

    r = client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=user)

    assert r.status_code == 200, r.json()


@pytest.fixture
def sid_fb(session) -> int:
    """기한 조건(in.finish_by)이 있는 A → B 일정."""
    return store(session, sample(), [finish_by("2027-04-30")])


def test_field_role_cannot_commit_conditions_even_when_approval_is_automatic(client, field_user, session, sid_fb):
    sid = sid_fb
    set_approval_mode(session, "auto")
    session.commit()
    body = {"base_version": 1, "changes": [{"id": "in.finish_by", "params": {"date": "2027-05-31"}}]}
    r = client.post(f"/api/schedules/{sid}/conditions/commit", json=body, headers=field_user)
    assert r.status_code == 403 and r.json()["code"] == "field_read_only"
    assert client.get(f"/api/schedules/{sid}", headers=field_user).json()["version"] == 1


def test_user_role_still_sets_weight_mode_and_commits_conditions(client, user, session, sid_fb):
    sid = sid_fb
    assert client.put(f"/api/schedules/{sid}/weight-mode", json={"mode": "manual"}, headers=user).status_code == 200
    set_approval_mode(session, "auto")
    session.commit()
    body = {"base_version": 1, "changes": [{"id": "in.finish_by", "params": {"date": "2027-05-31"}}]}
    r = client.post(f"/api/schedules/{sid}/conditions/commit", json=body, headers=user)
    assert r.status_code == 200, r.json()


# ── 에이전트 도구: 일정을 고치거나 승인함에 내는 도구는 현장 관리자에게 같은 글로 거절한다(리뷰 I-1) ─────

def _ctx(session, sid, role: str) -> ToolContext:
    registry.load_all()
    row = User(login_id=f"{role}-tool", name="박현장", role=role, password_hash=hash_password("x-pass-123"))
    session.add(row)
    session.commit()
    return ToolContext(session=session, user=row, schedule_id=sid, emit=lambda _: None)


def _scenario(session, sid) -> int:
    sc = Scenario(schedule_id=sid, base_version=1, name="복사본", source="agent", snapshot_json={}, conditions_json=[],
                  status="open", created_by="박현장")
    session.add(sc)
    session.commit()
    return sc.id


EDIT_TOOLS = [
    ("schedule.create_project", lambda s, sid: {"name": "새 현장"}),
    ("out.submit_change", lambda s, sid: {"title": "B 4일", "schedule_id": sid, "base_version": 1,
                                          "changes": [{"op": "update_activity", "id": "B", "od": 4}]}),
    ("scenario.submit", lambda s, sid: {"scenario_id": _scenario(s, sid)}),
    ("rules.propose", lambda s, sid: {"scope": "schedule", "why": "늘",
                                      "condition": {"kind": "text_only", "params": {}, "text": "타설 전날 알림"}}),
    ("schedule.record_actual", lambda s, sid: {"activity_id": "A", "progress": 0.5}),
]


@pytest.mark.parametrize(("name", "args"), EDIT_TOOLS, ids=[n for n, _ in EDIT_TOOLS])
async def test_field_role_agent_tools_that_change_a_schedule_are_refused(session, sid, name, args):
    ctx = _ctx(session, sid, "field")
    r = await registry.call(name, args(session, sid), ctx)
    assert not r.ok and r.error == FIELD_ONLY


QUESTION = {"id": "kind", "group": "범위", "question": "어떤 일정인가요?", "assumption": "건설 일정으로 봅니다."}
# 새 일정을 만드는 길(F4 재확인): 새 프로젝트 질문지·조건 뽑기·생성·공정표 가져오기·빈 프로젝트 — 도구에서 같은 글로 거절
NEW_SCHEDULE_TOOLS = [
    ("ask.questionnaire", {"purpose": "generate", "title": "새 프로젝트 — 분야와 범위", "questions": [QUESTION]}),
    ("generate.extract_conditions", {"text": "새 프로젝트 하나 만들어 줘", "domain": "construction", "level": "L2"}),
    ("generate.run", {"domain": "construction", "level": "L2", "request": "새 프로젝트 하나 만들어 줘"}),
    ("schedule.import", {"file_id": 1, "confirmed": True, "domain": "construction", "level": "L2"}),
    ("schedule.import", {"file_id": 1}),
    ("schedule.create_project", {"name": "새 현장"}),
]


@pytest.mark.parametrize(("name", "args"), NEW_SCHEDULE_TOOLS,
                         ids=[f"{n} {sorted(a)}" for n, a in NEW_SCHEDULE_TOOLS])
async def test_field_role_cannot_start_a_new_schedule_with_the_agent(session, sid, name, args):
    ctx = _ctx(session, sid, "field")
    r = await registry.call(name, args, ctx)
    assert not r.ok and r.error == FIELD_ONLY
    assert session.query(QuestionnaireRecord).count() == 0


async def test_field_role_still_reads_and_asks_other_questions(session, sid):
    ctx = _ctx(session, sid, "field")
    assert (await registry.call("schedule.read", {}, ctx)).ok
    asked = await registry.call("ask.questionnaire", {"purpose": "delay", "title": "지연 확인", "questions": [QUESTION]}, ctx)
    assert asked.ok, asked.error


async def test_field_role_new_project_request_ends_with_a_refusal_and_no_questionnaire(session, sid):
    """F4(재확인): 현장 관리자가 대화로 새 프로젝트를 청하면 질문지 없이 거절로 끝난다. 모델에게는 이 계정으로는
    일정을 만들 수 없다고 분명히 말하라는 글이 간다(지시문에도)."""
    ctx = _ctx(session, sid, "field")
    add_connection(session)
    chat = chats.create_chat(session, user_id=ctx.user.id)
    session.commit()
    ask = {"purpose": "generate", "title": "새 프로젝트 — 분야와 범위", "questions": [QUESTION]}
    llm = ScriptedLlm([calls("ask.questionnaire", ask), reply("이 계정으로는 새 일정을 만들 수 없습니다.")])
    client = LlmClient(session, transport=llm.transport)
    ev = [e async for e in run_turn(session, ctx.user, chat.id, "새 프로젝트 하나 만들어 줘", UiContext(None, None, None),
                                    llm=client)]
    assert [(e.data["tool"], e.data["ok"], e.data["error"]) for e in ev if e.type == "tool_end"] == [
        ("ask.questionnaire", False, FIELD_ONLY)]
    assert not any(e.type in ("questionnaire", "card") for e in ev)
    assert session.query(QuestionnaireRecord).count() == 0
    assert session.scalars(select(WorkflowRun)).one().status == "done"  # 답을 기다리지 않는다
    told = json.loads(llm.last_body["messages"][-1]["content"])["reflection"]
    assert "일정을 만들 수 없" in told
    assert "일정을 만들 수 없" in llm.bodies[0]["messages"][0]["content"]  # 지시문(지금 상황)
    assert [e.data["text"] for e in ev if e.type == "text"] == ["이 계정으로는 새 일정을 만들 수 없습니다."]


async def test_field_role_may_still_record_a_delay_with_the_agent(session, sid):
    ctx = _ctx(session, sid, "field")
    r = await registry.call("delay.record", {"activity_id": "A", "days": 2, "cause": "비"}, ctx)
    assert r.ok, r.error


async def test_user_role_agent_tools_are_unaffected(session, sid):
    ctx = _ctx(session, sid, "user")
    r = await registry.call("schedule.create_project", {"name": "새 현장"}, ctx)
    assert r.ok, r.error


# ── 연락처(계획 4 Task 72, require_contacts): 현장 관리자는 주소록을 열 수 없다. 역할을 먼저 보므로 없는 id 도 403 ─────

CONTACTS_NO = "현장 관리자는 연락처를 열 수 없습니다."
CONTACT_ROUTES = [
    ("GET", "/api/schedules/{sid}/contacts", None),
    ("POST", "/api/schedules/{sid}/contacts/companies", {"name": "가람건설"}),
    ("POST", "/api/schedules/{sid}/contacts/people", {"name": "김공정", "company_id": 1}),
    ("GET", "/api/schedules/{sid}/contacts/people/1", None),
    ("POST", "/api/schedules/{sid}/contacts/people/1/reveal", None),
]


@pytest.mark.parametrize(("method", "path", "body"), CONTACT_ROUTES, ids=[f"{m} {p}" for m, p, _ in CONTACT_ROUTES])
def test_field_role_cannot_open_contacts(client, field_user, sid, method, path, body):
    r = client.request(method, path.format(sid=sid), json=body, headers=field_user)

    assert r.status_code == 403, r.json()
    assert (r.json()["code"], r.json()["message"]) == ("field_no_contacts", CONTACTS_NO)


@pytest.mark.parametrize("who", ["user", "admin"])
def test_user_and_admin_open_contacts(client, request, sid, who):
    assert client.get(f"/api/schedules/{sid}/contacts", headers=request.getfixturevalue(who)).status_code == 200
