"""도구 rules.propose(내 규칙 제안 → 승인 → 저장), 생성 조립·대화 맥락의 내 규칙."""

from dataclasses import replace
from datetime import date

import pytest

from app.agent import context
from app.agent.context import UiContext, build_context, rejection_text
from app.agent.generation import generate
from app.llm.client import LlmClient
from app.store import chats, my_rules
from app.store.settings import set_approval_mode
from app.store.tables import Approval, MyRule, User
from app.tools.registry import call, list_tools
from tests import schedules
from tests.gen_doubles import SCHED_OK, START_FACT, WBS_OK, script
from tests.llm_doubles import FakeLiner, add_connection

TEXT = "층당 골조 10일 넘지 않기"
COND = {"kind": "max_duration", "params": {"days": 10}, "text": TEXT}
DOMAIN_RULE = {"scope": "domain", "condition": COND, "why": "늘 그렇게 잡음"}
SCHEDULE_RULE = {**DOMAIN_RULE, "scope": "schedule"}


@pytest.fixture
def ctx_sid(ctx, sid):
    """sid(A 3일 → B 2일, 분야 construction) 를 다루는 문맥."""
    return replace(ctx, schedule_id=sid)


def approve(client, admin, aid: int) -> None:
    r = client.post(f"/api/approvals/{aid}/decide", json={"decision": "approve", "note": ""}, headers=admin)
    assert r.status_code == 200, r.json()


def reject(client, admin, aid: int) -> None:
    r = client.post(f"/api/approvals/{aid}/decide", json={"decision": "reject", "note": "아님"}, headers=admin)
    assert r.status_code == 200, r.json()


def mine(cid: str = "mine.a1b2c3", text: str = TEXT, days: int = 10) -> dict:
    return {"id": cid, "layer": "mine", "kind": "max_duration", "params": {"days": days}, "text": text,
            "source": "내 규칙", "enabled": True, "overridden_by": None, "checkable": True}


def save_rule(session, *, scope="domain", domain="construction", schedule_id=None, cond=None, by="관리자") -> int:
    row = my_rules.create(session, scope=scope, domain=domain, schedule_id=schedule_id, condition_json=cond or mine(),
                          approval_id=None, created_by=by)
    session.commit()
    return row.id


@pytest.fixture
def saved_rule(session) -> int:
    return save_rule(session)


# ── 지시서 시험 ─────────────────────────────────────────────────────


async def test_domain_rule_needs_approval_then_saves(ctx_sid, session, client, admin):
    r = await call("rules.propose", DOMAIN_RULE, ctx_sid)
    assert r.ok, r.error
    row = session.get(Approval, r.output["approval_id"])
    assert (row.kind, row.reasons_json, session.query(MyRule).count()) == ("rule", ["rule_save"], 0)
    session.commit()
    approve(client, admin, row.id)
    rules = client.get("/api/rules?domain=construction", headers=admin).json()
    assert rules[0]["condition"]["layer"] == "mine" and rules[0]["condition"]["id"].startswith("mine.")
    assert rules[0]["scope"] == "domain"


async def test_schedule_rule_adds_a_mine_condition_in_a_new_version(ctx_sid, session, client, admin, sid):
    r = await call("rules.propose", SCHEDULE_RULE, ctx_sid)
    assert r.ok, r.error
    session.commit()
    approve(client, admin, r.output["approval_id"])
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["version"] == 2
    layers = client.get(f"/api/schedules/{sid}/conditions", headers=admin).json()["layers"]
    assert layers["mine"][0]["text"] == TEXT
    session.expire_all()
    saved = session.query(MyRule).one()
    assert (saved.scope, saved.schedule_id, saved.condition_json["id"]) == ("schedule", sid, layers["mine"][0]["id"])


async def test_wrong_kind_is_refused(ctx_sid):
    args = {**DOMAIN_RULE, "condition": {"kind": "finish_by", "params": {"date": "2027-11-30"}, "text": "준공"}}
    assert (await call("rules.propose", args, ctx_sid)).error == "내 규칙으로 둘 수 없는 종류입니다: finish_by"


async def test_rejected_rule_is_not_saved(ctx_sid, session, client, admin):
    r = await call("rules.propose", DOMAIN_RULE, ctx_sid)
    session.commit()
    reject(client, admin, r.output["approval_id"])
    session.expire_all()
    assert session.query(MyRule).count() == 0
    assert session.get(Approval, r.output["approval_id"]).status == "rejected"


async def test_generation_assembles_domain_rules(ctx, session):
    save_rule(session)
    save_rule(session, cond={**mine("mine.000002", "꺼 둔 규칙"), "kind": "text_only", "params": {}})
    my_rules.set_enabled(session, session.query(MyRule).all()[1], False)
    save_rule(session, domain="production", cond=mine("mine.000003", "다른 분야"))
    save_rule(session, scope="schedule", schedule_id=5, cond=mine("mine.000004", "한 일정만"))
    session.commit()
    liner = FakeLiner()
    add_connection(session)
    script(liner, WBS_OK, SCHED_OK)
    r = await generate(ctx, LlmClient(session, transport=liner.transport), domain="construction", level="L3",
                       request="5층 사무동 신축 일정", facts=[START_FACT])
    assert [c.text for c in r.conditions if c.layer == "mine"] == [TEXT]


def test_context_lists_my_rules(session, saved_rule, monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2026, 11, 20))
    admin = session.query(User).filter_by(login_id="admin").one()
    chat = chats.create_chat(session, user_id=admin.id).id
    assert "- 내 규칙 1개: 층당 골조 10일 넘지 않기" in build_context(session, admin, chat, UiContext())[0]["content"]


def test_only_owner_or_admin_deletes(client, user, admin, saved_rule):
    r = client.delete(f"/api/rules/{saved_rule}", headers=user)
    assert (r.status_code, r.json()["code"], r.json()["message"]) == (403, "not_owner", "만든 사람이나 관리자만 지울 수 있습니다.")
    assert client.delete(f"/api/rules/{saved_rule}", headers=admin).status_code == 200


# ── 더한 시험 ───────────────────────────────────────────────────────


def test_spec():
    spec = {t.name: t for t in list_tools()}["rules.propose"]
    assert (spec.program, spec.mutates) == ("conditions", True)


async def test_domain_rule_row_and_event(ctx_sid, session, events):
    r = await call("rules.propose", DOMAIN_RULE, ctx_sid)
    row = session.get(Approval, r.output["approval_id"])
    rule = {"scope": "domain", "domain": "construction", "text": TEXT, "kind": "max_duration", "params": {"days": 10}}
    assert (row.schedule_id, row.base_version, row.summary_json, row.snapshot_json) == (None, 0, {"rule": rule}, {})
    assert (row.link_kind, row.status, row.requested_kind, row.title) == ("rule", "pending", "agent", f"내 규칙 저장 — {TEXT}")
    cond = row.rule_json["condition"]
    assert (cond["layer"], cond["source"], cond["kind"], cond["params"], cond["text"]) == (
        "mine", "내 규칙", "max_duration", {"days": 10}, TEXT)
    assert len(cond["id"]) == len("mine.") + 6 and int(cond["id"][5:], 16) >= 0
    assert row.rule_json == {"scope": "domain", "domain": "construction", "schedule_id": None, "condition": cond}
    assert r.output == {"approval_id": row.id, "applied": False, "rule": row.rule_json}
    assert [e.type for e in events] == ["approval"]
    assert events[0].data == {"id": row.id, "title": row.title, "reasons": ["rule_save"], "summary": {"rule": rule}}


async def test_auto_mode_saves_a_domain_rule_at_once(ctx_sid, session, events):
    set_approval_mode(session, "auto")
    r = await call("rules.propose", DOMAIN_RULE, ctx_sid)
    assert r.output["applied"] is True
    row = session.get(Approval, r.output["approval_id"])
    saved = session.query(MyRule).one()
    assert (row.status, row.restore_to, saved.approval_id, saved.created_by, saved.scope) == (
        "auto", None, row.id, "관리자", "domain")
    assert saved.condition_json == r.output["rule"]["condition"]
    assert [e.data.get("kind", e.type) for e in events] == ["rule_saved"]


async def test_domain_can_be_named_without_a_schedule(ctx, session):
    r = await call("rules.propose", {**DOMAIN_RULE, "domain": "construction"}, ctx)
    assert r.ok, r.error
    assert session.get(Approval, r.output["approval_id"]).rule_json["domain"] == "construction"


async def test_schedule_rule_goes_through_propose(ctx_sid, session, sid):
    r = await call("rules.propose", SCHEDULE_RULE, ctx_sid)
    row = session.get(Approval, r.output["approval_id"])
    assert (row.kind, row.schedule_id, row.base_version, row.link_kind) == ("change", sid, 1, "rule")
    assert "rule_save" in row.reasons_json and "condition_changed" in row.reasons_json
    assert row.conditions_json[-1] == row.rule_json["condition"]
    assert row.rule_json["scope"] == "schedule" and row.rule_json["schedule_id"] == sid
    assert session.query(MyRule).count() == 0


async def test_rejected_schedule_rule_keeps_the_schedule(ctx_sid, session, client, admin, sid):
    r = await call("rules.propose", SCHEDULE_RULE, ctx_sid)
    session.commit()
    reject(client, admin, r.output["approval_id"])
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["version"] == 1
    session.expire_all()
    assert session.query(MyRule).count() == 0


@pytest.mark.parametrize(("args", "error"), [
    ({**DOMAIN_RULE, "condition": {**COND, "params": {}}}, "'days' 칸이 없습니다."),
    ({**DOMAIN_RULE, "condition": {**COND, "params": {"days": -1}}}, "'days' 칸 값이 올바르지 않습니다: 0 이상의 정수"),
    ({**DOMAIN_RULE, "domain": "space"}, "알 수 없는 분야입니다: space"),
])
async def test_bad_rules_are_refused_and_save_nothing(ctx_sid, session, args, error):
    r = await call("rules.propose", args, ctx_sid)
    assert (r.ok, r.error) == (False, error)
    assert session.query(Approval).count() == 0


async def test_domain_is_needed_without_a_schedule(ctx):
    assert (await call("rules.propose", DOMAIN_RULE, ctx)).error == "어느 분야의 규칙인지 알려 주세요."


async def test_schedule_scope_needs_a_schedule(ctx):
    assert (await call("rules.propose", {**SCHEDULE_RULE, "domain": "construction"}, ctx)).error == "대상 일정이 없습니다."


async def test_input_is_strict(ctx_sid):
    r = await call("rules.propose", {**DOMAIN_RULE, "condition": {**COND, "layer": "input"}}, ctx_sid)
    assert r.error.startswith("입력 형식 오류")
    long = await call("rules.propose", {**DOMAIN_RULE, "condition": {**COND, "text": "가" * 201}}, ctx_sid)
    assert long.error.startswith("입력 형식 오류")


def test_context_scopes(session, sid, monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2026, 11, 20))
    admin = session.query(User).filter_by(login_id="admin").one()
    chat = chats.create_chat(session, user_id=admin.id).id
    text = build_context(session, admin, chat, UiContext())[0]["content"]
    assert "- 대상 일정: 없음\n- 내 규칙: 없음" in text
    other = schedules.store(session, schedules.sample())
    save_rule(session)
    save_rule(session, scope="schedule", schedule_id=sid, cond=mine("mine.000002", "이 일정만"))
    save_rule(session, scope="schedule", schedule_id=other, cond=mine("mine.000003", "다른 일정"))
    save_rule(session, domain="production", cond=mine("mine.000004", "다른 분야"))
    text = build_context(session, admin, chat, UiContext(None, sid, None))[0]["content"]
    assert "\n- 내 규칙 2개: 층당 골조 10일 넘지 않기; 이 일정만" in text and "다른 일정" not in text
    lines = text.split("\n")
    assert lines[lines.index("- 내 규칙 2개: 층당 골조 10일 넘지 않기; 이 일정만") - 1].startswith("- 조건 ")
    nothing = build_context(session, admin, chat, UiContext())[0]["content"]
    assert "- 내 규칙 2개: 층당 골조 10일 넘지 않기; 다른 분야" in nothing  # 일정이 없으면 모든 분야 범위


def test_context_cuts_long_and_many_rules(session, monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2026, 11, 20))
    admin = session.query(User).filter_by(login_id="admin").one()
    chat = chats.create_chat(session, user_id=admin.id).id
    for n in range(12):
        save_rule(session, cond=mine(f"mine.{n:06x}", ("가" * 70) if n == 0 else f"규칙 {n}"))
    text = build_context(session, admin, chat, UiContext())[0]["content"]
    line = next(x for x in text.split("\n") if x.startswith("- 내 규칙"))
    assert line == "- 내 규칙 12개: " + "; ".join(["가" * 60, *(f"규칙 {n}" for n in range(1, 10))]) + " 외 2개"


def test_a_rejected_rule_is_proposed_again_with_rules_propose():
    rule = rejection_text({"approval_id": 3, "title": f"내 규칙 저장 — {TEXT}", "note": "범위를 이 일정으로"})
    assert "rules__propose" in rule and "out__submit_change" not in rule
    change = rejection_text({"approval_id": 4, "title": "B 기간 4일", "note": "안 됨"})
    assert "out__submit_change" in change and "rules__propose" not in change
