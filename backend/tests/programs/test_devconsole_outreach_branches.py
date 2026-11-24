"""개발 콘솔 ②(Task 109): 구조·흐름도의 연락 가지 · 도구 목록의 연락 도구 · 글 쪽 사용량. 읽기만 한다.

가지는 기록(실행 걸음·하네스 사건·답 줄)에서만 켜진다 — 설정이나 도구 등록 여부로 켜지 않는다.
사람·회사·번호는 모두 가상이다.
"""

import json
from datetime import UTC, datetime
from typing import get_args

from app.outreach.harness import events, toolsets
from app.outreach.harness.types import CallerClass, Medium, OutcomeCode, Ref
from app.security.crypto import encrypt
from app.store.tables_outreach import NotifyConnection, OutreachMessage, OutreachUsage
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY
from tests.programs.test_devconsole_api import get_turn, out, signal_turn

NOW = datetime.now(UTC)
OUTREACH_FLAGS = {"contact_lookup", "outreach_draft", "outreach_delegated", "outreach_unsure", "outreach_failed",
                  "outreach_blocked"}


def _lit(body: dict) -> set[str]:
    return set(body["structure"]["edges_lit"]) & OUTREACH_FLAGS


def _step_flags(body: dict) -> list[list[str]]:
    return [[f for f in (t.get("signals") or []) if f in OUTREACH_FLAGS] for t in body["timeline"] if t["kind"] == "tool"]


def _connection(session, **fields) -> NotifyConnection:
    values = {"name": "기본 연결", "base_url": "https://kat.invalid", "secret_ciphertext": encrypt(SENTINEL_KEY),
              "secret_last4": "9999", "account_id": "ACCT-0000", "sender_number": SENTINEL_DIGITS, "is_default": True,
              "status": "ok", "checked_at": NOW, "agent_sms": "delegate", "agent_kakao": "delegate",
              "agent_call": "delegate", **fields}
    row = NotifyConnection(**values)
    session.add(row)
    session.commit()
    return row


def _message(session, **fields) -> OutreachMessage:
    values = {"direction": "out", "channel": "sms", "origin": "agent", "origin_name": "에이전트", "body": "가상 글",
              "created_at": NOW, **fields}
    row = OutreachMessage(**values)
    session.add(row)
    session.commit()
    return row


def _detail(client, admin, kind: str, row_id: int) -> dict:
    r = client.get(f"/api/devconsole/outreach/{kind}/{row_id}", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


# ── 대화 턴의 가지 ──────────────────────────────────────────────────


def test_branches_light_only_from_recorded_steps(client, admin, session):
    _connection(session)  # 위임 설정이 모두 켜져 있어도
    plain = get_turn(client, admin, signal_turn(session, [{"tool": "schedule.read", "output_json": out(ok=True)}]))
    assert _lit(plain) == set() and _step_flags(plain) == [[]]

    body = get_turn(client, admin, signal_turn(session, [
        {"tool": "contacts.list", "output_json": out(total=1, items=[])},
        {"tool": "notify.draft_message", "output_json": out(message_id=3, status="draft", needs_approval=False, note="")},
        {"tool": "notify.draft_call", "status": "failed", "output_json": out(error="연락처를 찾을 수 없습니다.")},
    ]))
    assert _lit(body) == {"contact_lookup", "outreach_draft"}  # 보내기 걸음이 없으니 위임 가지는 꺼져 있다
    assert _step_flags(body) == [["contact_lookup"], ["outreach_draft"], []]  # 끝나지 않은 초안은 켜지 않는다


def test_delegated_vs_blocked_follow_the_recorded_outcome(client, admin, session):
    passed = get_turn(client, admin, signal_turn(session, [
        {"tool": "notify.send_message", "output_json": out(outcome="accepted", message="보냈습니다", scheduled_at=None)},
        {"tool": "notify.place_call", "output_json": out(outcome="queued", message="줄에 넣었습니다", scheduled_at=None)},
        {"tool": "notify.send_message", "output_json": out(outcome="scheduled", message="예약", scheduled_at="2027-03-02")},
    ]))
    assert _lit(passed) == {"outreach_delegated"}
    assert _step_flags(passed) == [["outreach_delegated"]] * 3

    blocked = get_turn(client, admin, signal_turn(session, [
        {"tool": "notify.send_message", "output_json": out(outcome="blocked_test", message="시험 모드", scheduled_at=None)},
        {"tool": "notify.place_call", "output_json": out(outcome="needs_approval", message="승인", scheduled_at=None)},
        {"tool": "notify.send_message", "status": "failed", "output_json": out(error="이 대화에서 만든 초안만 보낼 수 있습니다.")},
        {"tool": "notify.send_message", "output_json": out(message="결과 코드가 없는 기록")},
    ]))
    assert _lit(blocked) == {"outreach_blocked"}
    assert _step_flags(blocked) == [["outreach_blocked"], ["outreach_blocked"], [], []]


def test_unknown_and_failed_results_are_not_shown_as_blocked(client, admin, session):
    """문을 지나간 뒤 결과를 모름(unsure)·통로가 보내지 못함(failed)은 「문이 막음」이 아니다. 중복은 문이 막은 것."""
    body = get_turn(client, admin, signal_turn(session, [
        {"tool": "notify.send_message", "output_json": out(outcome="unsure", message="보냈는지 확인 필요", scheduled_at=None)},
        {"tool": "notify.place_call", "output_json": out(outcome="failed", message="보내지 못했습니다", scheduled_at=None)},
        {"tool": "notify.send_message", "output_json": out(outcome="duplicate", message="같은 연락", scheduled_at=None)},
    ]))
    assert _step_flags(body) == [["outreach_unsure"], ["outreach_failed"], ["outreach_blocked"]]
    assert _lit(body) == {"outreach_unsure", "outreach_failed", "outreach_blocked"}


def test_passing_outcomes_are_outcome_codes():
    from app.programs.devconsole import outreach_branches

    assert outreach_branches.PASSED <= set(get_args(OutcomeCode))


# ── 연락 하나의 흐름도 ──────────────────────────────────────────────


def _record(session, ref: Ref, rule: str, verdict: str, detail: str | None = None) -> None:
    events.record(session, ref, rule, verdict, detail)
    session.commit()


def test_inbound_handled_needs_admit_event_and_linked_reply(client, admin, session):
    inbound = _message(session, direction="in", origin="peer", origin_name="", peer_number=SENTINEL_DIGITS,
                       status="received")
    _record(session, Ref("message", inbound.id), "admission", "allowed", "known_caller")
    _record(session, Ref("message", inbound.id), "tool:find_contact", "allowed", "q")
    _record(session, Ref("message", inbound.id), "scope_denied", "blocked", "tool=schedule_fact 범위 밖")

    alone = _detail(client, admin, "message", inbound.id)
    assert alone["branches_lit"] == []  # 답 줄이 없다
    assert [n["key"] for n in alone["flow"]] == ["inbound", "tool", "post_check", "gate", "channel"]
    assert [n["label"] for n in alone["flow"]] == ["들어오는 문", "도구", "뒤 확인", "나가는 문", "통로"]
    nodes = {n["key"]: n for n in alone["flow"]}
    assert nodes["inbound"]["count"] == 1 and nodes["inbound"]["verdicts"] == [
        {"verdict": "allowed", "label": "지나감", "count": 1}]
    assert nodes["tool"]["count"] == 2
    assert {(v["verdict"], v["count"]) for v in nodes["tool"]["verdicts"]} == {("allowed", 1), ("blocked", 1)}
    assert nodes["gate"]["count"] == 0 and nodes["gate"]["verdicts"] == []

    reply = _message(session, kind="auto_reply", reply_to_id=inbound.id, status="accepted")
    _record(session, Ref("message", reply.id), "channel_choice", "allowed", "sms")
    _record(session, Ref("message", reply.id), "delivery", "noted", "모름")
    linked = _detail(client, admin, "message", inbound.id)
    assert linked["branches_lit"] == ["inbound_handled"]
    reply_view = _detail(client, admin, "message", reply.id)
    assert reply_view["branches_lit"] == ["inbound_handled"]  # 답 줄 쪽에서도 같은 짝
    by_key = {n["key"]: n for n in reply_view["flow"]}
    assert by_key["gate"]["count"] == 1 and by_key["channel"]["verdicts"] == [
        {"verdict": "noted", "label": "확인 필요", "count": 1}]

    # 받기 판정이 막음이고 고정 안내가 걸린 줄은 「응대」가 아니라 「막고 안내함」
    refused = _message(session, direction="in", origin="peer", origin_name="", peer_number=SENTINEL_DIGITS,
                       status="received")
    _record(session, Ref("message", refused.id), "admission", "blocked", "unknown_not_accepted")
    notice = _message(session, kind="notice", reply_to_id=refused.id, status="accepted")
    assert _detail(client, admin, "message", refused.id)["branches_lit"] == ["inbound_refused"]
    assert _detail(client, admin, "message", notice.id)["branches_lit"] == ["inbound_refused"]
    # 받기 판정 사건이 없는 받은 줄은 답이 걸려 있어도 켜지지 않는다
    bare = _message(session, direction="in", origin="peer", origin_name="", peer_number=SENTINEL_DIGITS,
                    status="received")
    _message(session, kind="auto_reply", reply_to_id=bare.id, status="accepted")
    assert _detail(client, admin, "message", bare.id)["branches_lit"] == []
    # 모양이 틀린 harness_json 이어도 500 이 아니다
    odd = _message(session, direction="in", origin="peer", origin_name="", peer_number=SENTINEL_DIGITS,
                   status="received", harness_json={"rule": "admission"})
    _message(session, kind="auto_reply", reply_to_id=odd.id, status="accepted")
    assert _detail(client, admin, "message", odd.id)["branches_lit"] == []


def test_answered_inbound_call_has_the_flow_and_the_answered_branch(client, admin, session):
    from app.store.tables_outreach import OutreachCall

    call = OutreachCall(direction="in", origin="peer", origin_name="", purpose="", status="completed", created_at=NOW)
    session.add(call)
    session.commit()
    _record(session, Ref("call", call.id), "admission", "allowed", "known_caller")
    body = _detail(client, admin, "call", call.id)
    assert body["branches_lit"] == ["call_answered"] and body["flow"][0]["count"] == 1  # 받은 통화의 가지는 Task 98(문자 가지 없음)


# ── 도구 목록 ───────────────────────────────────────────────────────


def _catalog_tools(client, admin) -> dict[str, dict]:
    r = client.get("/api/devconsole/catalog", headers=admin)
    assert r.status_code == 200, r.text
    return {t["name"]: t for t in r.json()["registry"]["tools"]}


def test_registry_lists_harness_tools_with_classes_media_and_roles(client, admin):
    tools = _catalog_tools(client, admin)
    harness = {name: t for name, t in tools.items() if name.startswith("outreach.")}
    assert sorted(harness) == sorted(f"outreach.{n}" for n in toolsets.ALL) and len(harness) == 12
    for name, t in harness.items():
        bare = name.removeprefix("outreach.")
        assert t["category"] == "연락 하네스 도구" and t["toggle"] is False
        assert t["role_note"] == "음성·글 에이전트 — 사람이 직접 부르지 않음"
        assert t["llm_name"] == bare
        (definition,) = toolsets.tool_defs([bare])
        assert t["description"] == definition.description and t["schema"] == definition.json_schema()
        expected = {cls for cls in get_args(CallerClass) for m in get_args(Medium) if bare in toolsets.for_class(cls, m)}
        assert set(t["classes"]) == expected
    assert "unknown" not in harness["outreach.schedule_fact"]["classes"]
    assert "internal" in harness["outreach.schedule_fact"]["classes"]
    assert harness["outreach.end_call"]["media"] == ["call"]
    assert harness["outreach.confirm_person"]["classes"] == ["outbound"]
    assert harness["outreach.find_contact"]["media"] == ["sms", "call"]
    assert set(harness["outreach.take_message"]["classes"]) >= {"unknown", "withheld", "do_not_contact"}


def test_chat_agent_notify_tools_carry_their_role_note(client, admin):
    tools = _catalog_tools(client, admin)
    for name in ("contacts.list", "notify.draft_message", "notify.draft_call", "notify.status"):
        assert tools[name]["role_note"] == "관리자·사용자 — 현장 관리자 불가", name
        assert tools[name]["roles"] == ["admin", "user"], name
        assert tools[name].get("toggle", True) is True
    for name in ("notify.send_message", "notify.place_call"):  # 위임 도구(Task 81) — 등록돼 있을 때만
        if name in tools:
            assert tools[name]["role_note"] == "그 채널이 위임일 때만 보임"
    assert "role_note" not in tools["schedule.read"] or tools["schedule.read"]["role_note"] is None


def test_harness_tool_cannot_be_switched_off(client, admin):
    r = client.put("/api/devconsole/tools/outreach.end_call", json={"enabled": False}, headers=admin)
    assert r.status_code == 404  # 등록부 도구가 아니다 — 끄기 길이 없다


# ── 사용량 ──────────────────────────────────────────────────────────


def test_usage_shows_auto_replies_and_text_model_usage(client, admin, session):
    _message(session, kind="auto_reply", status="accepted", claimed_at=NOW)
    _message(session, status="accepted", claimed_at=NOW)
    session.add_all([
        OutreachUsage(at=NOW, kind="text_reply", model="m-a", input_tokens=120, output_tokens=30, cost=0.002),
        OutreachUsage(at=NOW, kind="text_reply", model="m-a", input_tokens=80, output_tokens=20, cost=None),
        OutreachUsage(at=NOW, kind="translation", model="m-b", input_tokens=40, output_tokens=10, cost=None),
        OutreachUsage(at=NOW, kind="voice_model", model="v", input_tokens=999, output_tokens=999, seconds=30, cost=1.5),
    ])
    session.commit()
    body = client.get("/api/devconsole/usage?days=7", headers=admin).json()["outreach"]
    assert body["auto_replies"] == 1
    rows = {r["kind"]: r for r in body["text_models"]}
    assert list(rows) == ["text_reply", "draft", "translation"]  # 음성 쪽 종류는 싣지 않는다
    assert rows["text_reply"] == {"kind": "text_reply", "count": 2, "input_tokens": 200, "output_tokens": 50,
                                  "cost": 0.002}  # 요금은 모델이 알려 준 것만
    assert rows["draft"] == {"kind": "draft", "count": 0, "input_tokens": 0, "output_tokens": 0, "cost": None}
    assert rows["translation"]["cost"] is None and rows["translation"]["count"] == 1
    assert "voice_model" not in json.dumps(body["text_models"])  # 음성 쪽은 calls 칸(Task 110)
