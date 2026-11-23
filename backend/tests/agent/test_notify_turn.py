"""대화 턴에서의 위임 발송(계획 4 Task 81): 권한에 따라 모델에게 보이는 도구, 숨긴 도구를 그래도 부른 턴, 끝에서 끝까지
번호·키가 trace·대화 저장·모델 요청에 없는 것, 도구가 실패해 되돌려도 문이 적은 줄은 남는 것.

LLM 은 ScriptedLlm, 통로는 fake_channel 뿐이다(진짜 제공사·LLM·네트워크 없음).
"""

import json
import re
from datetime import datetime

import pytest
from sqlalchemy import func, select, text

from app.agent.context import UiContext
from app.agent.loop import run_turn
from app.llm.client import LlmClient
from app.outreach import hours, phone
from app.outreach.harness import events as harness_events
from app.outreach.harness import gate
from app.outreach.harness.types import Ref
from app.store import chats
from app.store.tables import ChatMessage, User
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    NotifyConnection,
    OutreachMessage,
)
from app.tools import registry
from app.tools.notify import send_message
from tests.llm_doubles import add_connection
from tests.loop_doubles import ScriptedLlm, calls, reply
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY

KST = hours.KST
WORK = datetime(2026, 11, 27, 10, 0, tzinfo=KST)  # 금요일 10시 — 근무 중
ACCOUNT = "acct-test-0001"
CONTACT_TOOLS = {"contacts__list", "notify__draft_message", "notify__draft_call", "notify__status",
                 "notify__send_message", "notify__place_call"}
SEP = r"[\s\-.()]{0,2}"
PHONE_ANY = re.compile(SEP.join(SENTINEL_DIGITS[1:]))  # 010-0000-0199 · 01000000199 · +82 10 0000 0199 …


@pytest.fixture(autouse=True)
def all_tools():
    registry.load_all()


@pytest.fixture(autouse=True)
def at_work(monkeypatch):
    monkeypatch.setattr(send_message, "_now", lambda: WORK)


@pytest.fixture
def admin_user(session) -> User:
    return session.scalars(select(User).where(User.login_id == "admin")).one()


@pytest.fixture
def run(session):
    """run(대본 LLM, 글, user=…, ui=…) → (턴의 사건, 대화 id). 대화는 그 사용자의 새 대화. LLM 기본 연결이 있다."""
    add_connection(session)

    async def go(llm: ScriptedLlm, said: str, *, user: User, ui: UiContext | None = None, chat_id: int | None = None):
        if chat_id is None:
            chat_id = chats.create_chat(session, user_id=user.id).id
            session.commit()
        client = LlmClient(session, transport=llm.transport)
        turn = run_turn(session, user, chat_id, said, ui or UiContext(), llm=client, max_steps=6)
        return [e async for e in turn], chat_id

    return go


def _conn(session, **over) -> NotifyConnection:
    values = {"name": "시험 연결", "base_url": "https://kat.invalid", "secret_ciphertext": SENTINEL_KEY,
              "secret_last4": "9999", "account_id": ACCOUNT, "sender_number": SENTINEL_DIGITS,
              "allow_numbers_json": [SENTINEL_DIGITS], "handoff_number": SENTINEL_DIGITS, "is_default": True,
              "status": "ok", "test_mode": True, "agent_sms": "delegate", "agent_kakao": "approve",
              "agent_call": "approve", **over}
    row = NotifyConnection(**values)
    session.add(row)
    session.commit()
    return row


def _person(session, sid: int) -> Contact:
    firm = ContactCompany(schedule_id=sid, name="가람철근", trade="철근", note=f"대표 {SENTINEL_DIGITS}")
    session.add(firm)
    session.flush()
    who = Contact(schedule_id=sid, company_id=firm.id, name="김공정", role_title="공무", phone=SENTINEL_DIGITS,
                  note=f"급하면 {SENTINEL_DIGITS} 로", can_sms=True, can_kakao=True,
                  can_call=phone.can_call(SENTINEL_DIGITS))
    session.add(who)
    session.commit()
    return who


def _field(session) -> User:
    user = User(login_id="field1", name="박현장", role="field", password_hash="x")
    session.add(user)
    session.commit()
    return user


def _tool_names(body: dict) -> set[str]:
    return {t["function"]["name"] for t in body.get("tools") or []}


def _saved_tool_results(session, chat_id: int) -> list[dict]:
    session.expire_all()
    rows = session.scalars(select(ChatMessage).where(ChatMessage.session_id == chat_id, ChatMessage.role == "tool"))
    return [r.content_json for r in rows]


def _saved_cards(session, chat_id: int) -> list[dict]:
    session.expire_all()
    rows = session.scalars(select(ChatMessage).where(ChatMessage.session_id == chat_id, ChatMessage.role == "event"))
    return [r.content_json["data"] for r in rows if r.content_json.get("type") == "card"]


async def test_send_tools_are_hidden_unless_delegated(session, run, admin_user):
    """모델에게 보내는 도구 목록: 연결 없음·현장 관리자 → 연락 도구 전부 없음, 승인 받기 → 보내기 도구 없음, 위임 → 그 채널 것만."""
    seen: list[set[str]] = []

    def turn(llm_bodies: list[dict]) -> None:
        names = {frozenset(_tool_names(b)) for b in llm_bodies}
        assert len(names) == 1  # 한 턴 안의 모든 호출이 같은 목록
        seen.append(set(next(iter(names))))

    llm = ScriptedLlm([reply("네")])
    await run(llm, "안녕", user=admin_user)  # 연결 없음
    turn(llm.bodies)
    conn = _conn(session, agent_sms="approve", agent_kakao="approve", agent_call="approve")
    llm = ScriptedLlm([reply("네")])
    await run(llm, "안녕", user=admin_user)
    turn(llm.bodies)
    conn.agent_kakao = "delegate"
    session.commit()
    llm = ScriptedLlm([reply("네")])
    await run(llm, "안녕", user=admin_user)
    turn(llm.bodies)
    conn.agent_sms, conn.agent_kakao, conn.agent_call = "approve", "approve", "delegate"
    session.commit()
    llm = ScriptedLlm([reply("네")])
    await run(llm, "안녕", user=admin_user)
    turn(llm.bodies)
    conn.agent_sms, conn.agent_kakao, conn.agent_call = "delegate", "delegate", "delegate"
    session.commit()
    llm = ScriptedLlm([reply("네")])
    await run(llm, "안녕", user=admin_user)
    turn(llm.bodies)
    llm = ScriptedLlm([reply("네")])
    await run(llm, "안녕", user=_field(session))  # 현장 관리자 — 모두 위임이어도
    turn(llm.bodies)

    every = {t["function"]["name"] for t in registry.as_llm_tools()}
    assert CONTACT_TOOLS <= every
    contact = [s & CONTACT_TOOLS for s in seen]
    assert contact == [
        set(),
        CONTACT_TOOLS - {"notify__send_message", "notify__place_call"},
        CONTACT_TOOLS - {"notify__place_call"},
        CONTACT_TOOLS - {"notify__send_message"},
        CONTACT_TOOLS,
        set(),
    ]
    assert all(s - CONTACT_TOOLS == every - CONTACT_TOOLS for s in seen)  # 다른 도구는 그대로


async def test_trace_counts_the_tools_the_model_saw(session, run, admin_user):
    _conn(session, agent_sms="approve", agent_kakao="approve", agent_call="approve")
    llm = ScriptedLlm([reply("네")])
    _, chat_id = await run(llm, "안녕", user=admin_user)
    found = session.execute(text("SELECT input_text FROM trace_events WHERE chat_session_id = :c AND kind = 'context'"),
                            {"c": chat_id}).scalar_one()
    assert json.loads(found)["tool_count"] == len(_tool_names(llm.bodies[0]))


async def test_hidden_tool_called_anyway_is_blocked_by_gate(session, sid, run, admin_user, fake_channel):
    _conn(session, agent_sms="approve", agent_kakao="approve", agent_call="approve")
    who = _person(session, sid)
    chat_id = chats.create_chat(session, user_id=admin_user.id).id
    row = OutreachMessage(schedule_id=sid, contact_id=who.id, direction="out", channel="sms", body="내일 타설 됩니까",
                          origin="agent", origin_name="에이전트", status="draft", chat_session_id=chat_id)
    session.add(row)
    session.commit()
    llm = ScriptedLlm([calls("notify.send_message", {"message_id": row.id}), reply("초안을 만들었습니다. [보내기]를 눌러 주세요.")])
    ev, _ = await run(llm, "보내 줘", user=admin_user, ui=UiContext("contacts", sid, None), chat_id=chat_id)
    assert "notify__send_message" not in _tool_names(llm.bodies[0])  # 첫 겹: 보이지 않는다
    assert fake_channel.delivered == []  # 둘째 겹: 문이 막는다
    session.expire_all()
    stored = session.get(OutreachMessage, row.id)
    assert (stored.status, stored.send_mode, stored.approved_by) == ("draft", None, None)
    [result] = _saved_tool_results(session, chat_id)
    assert result["ok"] is True and json.loads(result["content"])["outcome"] == "needs_approval"
    [card] = _saved_cards(session, chat_id)
    assert (card["kind"], card["outcome"]) == ("outreach_sent", "needs_approval")
    assert [e["rule"] for e in harness_events.of(session, Ref("message", row.id))] == ["permission"]
    assert [e.type for e in ev][-1] == "done" and "error" not in [e.type for e in ev]


async def test_turn_leaves_no_phone_or_key_in_trace_and_messages(session, sid, run, admin_user, fake_channel):
    """목록 → 초안 → 위임 보내기 한 턴. 번호(어느 꼴이든)·키·Account ID·가린 꼴이 trace·대화 저장·실행 기록·모델 요청에 없다."""
    _conn(session)
    who = _person(session, sid)
    llm = ScriptedLlm([
        calls("contacts.list", {"query": "김공정"}, call_id="c1"),
        calls("notify.draft_message", {"contact_id": who.id, "channel": "sms", "body": "내일 3층 타설 가능하신가요"},
              call_id="c2"),
        calls("notify.send_message", {"message_id": 1}, call_id="c3"),
        reply("김공정 공무님께 문자를 보냈습니다(접수)."),
    ])
    ev, chat_id = await run(llm, "김공정 공무에게 내일 타설 되는지 문자 보내 줘", user=admin_user,
                            ui=UiContext("contacts", sid, None))
    session.expire_all()
    sent = session.get(OutreachMessage, 1)
    assert (sent.chat_session_id, sent.origin, sent.status, sent.send_mode) == (chat_id, "agent", "accepted", "delegated")
    assert [d.row_id for d in fake_channel.delivered] == [1]
    assert "error" not in [e.type for e in ev]

    dumps = [json.dumps(llm.bodies, ensure_ascii=False)]
    for table in ("trace_events", "chat_messages", "workflow_runs", "workflow_steps"):
        rows = session.execute(text(f"SELECT * FROM {table}")).all()  # 표 이름은 위 고정 목록
        assert rows, table
        dumps.append(json.dumps([list(r) for r in rows], ensure_ascii=False, default=str))
    dumps.append(json.dumps([e.data for e in ev], ensure_ascii=False, default=str))
    for found in dumps:
        assert PHONE_ANY.search(found) is None
        assert SENTINEL_KEY not in found and ACCOUNT not in found and "****" not in found


async def test_tool_failure_rollback_does_not_undo_gate_rows(session, sid, run, admin_user, fake_channel, monkeypatch):
    """문이 보낸 뒤에 도구가 실패하면 루프는 도구의 쓰기를 되돌린다 — 문이 자기 세션으로 적은 줄·사건은 남는다."""
    _conn(session)
    who = _person(session, sid)
    chat_id = chats.create_chat(session, user_id=admin_user.id).id
    row = OutreachMessage(schedule_id=sid, contact_id=who.id, direction="out", channel="sms", body="내일 타설 됩니까",
                          origin="agent", origin_name="에이전트", status="draft", chat_session_id=chat_id)
    session.add(row)
    session.commit()
    real = gate.dispatch

    async def then_fail(kind, row_id, actor, *, now=None):
        await real(kind, row_id, actor, now=now)
        session.add(ContactCompany(schedule_id=sid, name="되돌릴표식", trade="x"))  # 도구 세션의 쓰기
        session.flush()
        raise RuntimeError("문 뒤에서 실패")

    monkeypatch.setattr(gate, "dispatch", then_fail)
    llm = ScriptedLlm([calls("notify.send_message", {"message_id": row.id}), reply("확인이 필요합니다.")])
    await run(llm, "보내 줘", user=admin_user, ui=UiContext("contacts", sid, None), chat_id=chat_id)
    session.expire_all()
    stored = session.get(OutreachMessage, row.id)
    assert (stored.status, stored.send_mode) == ("accepted", "delegated")
    assert len(fake_channel.delivered) == 1
    assert [e["rule"] for e in harness_events.of(session, Ref("message", row.id))] == ["channel_choice", "delivery"]
    assert session.scalar(select(func.count()).select_from(ContactCompany).where(ContactCompany.name == "되돌릴표식")) == 0
    [result] = _saved_tool_results(session, chat_id)
    assert result["ok"] is False
