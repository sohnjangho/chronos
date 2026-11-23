"""대화 에이전트의 위임 발송 도구(계획 4 Task 81): notify.send_message · notify.place_call, 그리고 policy.hidden_tools.

지키는 것: 이 대화가 만든 에이전트 초안만 보낸다(사람의 초안·다른 대화·다른 일정·끝난 줄은 없는 것과 같은 글) · 판정은
모두 나가는 문(Actor agent)이 한다 — 도구는 send_mode·approved_by·status 를 쓰지 않고, 문에 넣기 전에 ctx.session 에
아무것도 쓰지 않는다 · 한 번 부르면 문도 한 번 · 결과는 문의 판정 그대로(확인 필요는 보냄이 아니다) · 카드에 번호 없음.
통로는 fake_channel 뿐이다(진짜 제공사·LLM·네트워크 없음).
"""

import json
from datetime import datetime

import pytest
from sqlalchemy import event, func, select

from app.outreach import hours, phone, policy
from app.outreach.harness import gate
from app.outreach.harness.types import Delivered
from app.store import chats
from app.store.tables import EvidenceItem, EvidenceLink, EvidenceSearch, User
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
)
from app.tools import registry
from app.tools.context import ToolContext
from app.tools.notify import send_message
from tests import schedules
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY

KST = hours.KST
WORK = datetime(2026, 11, 27, 10, 0, tzinfo=KST)  # 금요일 10시 — 근무 중
OFF = datetime(2026, 11, 27, 19, 0, tzinfo=KST)  # 금요일 19시 — 근무 밖
NOT_YOURS = "이 대화에서 만든 초안만 보낼 수 있습니다."
FIELD_REFUSAL = "현장 관리자는 연락처를 쓸 수 없습니다."
SEND_TOOLS = frozenset({"notify.send_message", "notify.place_call"})
SENT_CARD_KEYS = {"kind", "schedule_id", "contact", "channel", "outcome", "message"}


@pytest.fixture(autouse=True)
def at_work(monkeypatch):
    monkeypatch.setattr(send_message, "_now", lambda: WORK)


@pytest.fixture
def dispatched(monkeypatch) -> list:
    """문에 넣은 것 (kind, row_id, actor) — 넣는 순간 ctx 의 세션에 쓰지 않은 것이 없어야 한다(spy 가 본다)."""
    seen: list = []
    real = gate.dispatch

    async def spy(kind, row_id, actor, *, now=None):
        seen.append((kind, row_id, actor, now))
        return await real(kind, row_id, actor, now=now)

    monkeypatch.setattr(gate, "dispatch", spy)
    return seen


@pytest.fixture
def admin_user(session) -> User:
    return session.scalars(select(User).where(User.login_id == "admin")).one()


@pytest.fixture
def chat_id(session, admin_user) -> int:
    chat = chats.create_chat(session, user_id=admin_user.id)
    session.commit()
    return chat.id


@pytest.fixture
def events() -> list:
    return []


@pytest.fixture
def tctx(session, sid, admin_user, chat_id, events) -> ToolContext:
    return ToolContext(session=session, user=admin_user, schedule_id=sid, emit=events.append, chat_session_id=chat_id)


def _conn(session, **over) -> NotifyConnection:
    """기본 연결: ok · 시험 모드 끔 · 문자·카카오톡·전화 모두 위임(시험이 바꾼다). 키·Account ID·발신번호는 표식 값."""
    values = {"name": "시험 연결", "base_url": "https://kat.invalid", "secret_ciphertext": SENTINEL_KEY,
              "secret_last4": "9999", "account_id": "acct-test-0001", "sender_number": "07000000000",
              "allow_numbers_json": [], "is_default": True, "status": "ok", "test_mode": False,
              "agent_sms": "delegate", "agent_kakao": "delegate", "agent_call": "delegate", **over}
    row = NotifyConnection(**values)
    session.add(row)
    session.commit()
    return row


def _person(session, sid: int, *, number: str = SENTINEL_DIGITS, name: str = "김공정") -> Contact:
    firm = ContactCompany(schedule_id=sid, name="가람철근", trade="철근")
    session.add(firm)
    session.flush()
    who = Contact(schedule_id=sid, company_id=firm.id, name=name, role_title="공무", phone=number,
                  can_sms=phone.can_sms(number), can_kakao=phone.can_sms(number), can_call=phone.can_call(number))
    session.add(who)
    session.commit()
    return who


def _draft(session, who: Contact, chat_id: int | None, **over) -> OutreachMessage:
    """에이전트가 그 대화에서 만든 문자 초안(Task 80 의 줄 꼴)."""
    values = {"schedule_id": who.schedule_id, "contact_id": who.id, "direction": "out", "channel": "sms",
              "kind": "normal", "body": "내일 3층 타설 가능하신가요", "origin": "agent", "origin_name": "에이전트",
              "status": "draft", "chat_session_id": chat_id, **over}
    row = OutreachMessage(**values)
    session.add(row)
    session.commit()
    return row


def _call_draft(session, who: Contact, chat_id: int | None, **over) -> OutreachCall:
    values = {"schedule_id": who.schedule_id, "contact_id": who.id, "direction": "out", "purpose": "타설 일정 확인",
              "questions_json": ["내일 오전에 됩니까"], "origin": "agent", "origin_name": "에이전트", "status": "draft",
              "chat_session_id": chat_id, **over}
    row = OutreachCall(**values)
    session.add(row)
    session.commit()
    return row


def _reread(session, row):
    session.expire_all()
    return session.get(type(row), row.id)


def _cards(events: list) -> list[dict]:
    return [e.data for e in events if e.type == "card"]


def _no_phone(value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, default=str)
    digits = "".join(ch for ch in text if ch.isdigit())
    assert SENTINEL_DIGITS not in digits and SENTINEL_DIGITS[1:] not in digits
    assert SENTINEL_KEY not in text and "acct-test-0001" not in text and "****" not in text


# ── policy.hidden_tools ──────────────────────────────────────────────


def _contact_tools() -> frozenset[str]:
    registry.load_all()
    return frozenset(s.name for s in registry.list_tools(enabled_only=False)
                     if s.name.startswith(("contacts.", "notify.")))


def test_hidden_tools_cover_every_contact_tool_without_a_connection_or_for_field(session, admin_user):
    names = _contact_tools()
    assert {"contacts.list", "notify.draft_message", "notify.draft_call", "notify.status", *SEND_TOOLS} <= names
    assert policy.hidden_tools(session, admin_user) == names  # 연결 없음
    _conn(session)
    assert policy.hidden_tools(session, admin_user) == frozenset()  # 모두 위임
    field = User(login_id="field1", name="박현장", role="field", password_hash="x")
    session.add(field)
    session.commit()
    assert policy.hidden_tools(session, field) == names  # 현장 관리자는 위임이어도 전부


@pytest.mark.parametrize(("sms", "kakao", "call", "hidden"), [
    ("approve", "approve", "approve", SEND_TOOLS),
    ("delegate", "approve", "approve", {"notify.place_call"}),
    ("approve", "delegate", "approve", {"notify.place_call"}),
    ("approve", "approve", "delegate", {"notify.send_message"}),
    ("delegate", "delegate", "delegate", set()),
    ("yes", "DELEGATE", None, SEND_TOOLS),  # 모르는 값·빈 값은 승인 받기로 읽는다
    ("delegate ", "", "delegated", SEND_TOOLS),
])
def test_hidden_tools_follow_each_channel_permission(session, admin_user, sms, kakao, call, hidden):
    registry.load_all()
    _conn(session, agent_sms=sms, agent_kakao=kakao, agent_call=call)
    assert policy.hidden_tools(session, admin_user) == frozenset(hidden)


def test_hidden_tools_read_only_the_default_connection(session, admin_user):
    registry.load_all()
    _conn(session, name="다른 연결", is_default=False)  # 위임이지만 기본 연결이 아니다(먼저 만든 줄)
    _conn(session, agent_sms="approve", agent_kakao="approve", agent_call="approve")
    assert policy.hidden_tools(session, admin_user) == SEND_TOOLS


def test_hidden_tools_cost_at_most_two_queries(session, admin_user):
    registry.load_all()
    _conn(session)
    seen: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        seen.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", count)
    try:
        policy.hidden_tools(session, admin_user)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert 1 <= len(seen) <= 2


def test_llm_tool_list_leaves_out_hidden_names():
    registry.load_all()
    every = {t["function"]["name"] for t in registry.as_llm_tools()}
    shown = {t["function"]["name"] for t in registry.as_llm_tools(hidden=SEND_TOOLS)}
    assert every - shown == {"notify__send_message", "notify__place_call"}


# ── 보내기 ──────────────────────────────────────────────────────────


async def test_delegated_send_is_recorded_as_delegated(session, sid, tctx, events, fake_channel, dispatched):
    _conn(session)
    who = _person(session, sid)
    row = _draft(session, who, tctx.chat_session_id)
    result = await registry.call("notify.send_message", {"message_id": row.id}, tctx)
    assert result.ok, result.error
    assert result.output == {"outcome": "accepted", "message": "보냈습니다", "scheduled_at": None}
    row = _reread(session, row)
    assert row.send_mode == "delegated" and row.origin == "agent"
    assert row.status == "accepted" and row.approved_by is None
    assert [d.row_id for d in fake_channel.delivered] == [row.id]
    assert len(dispatched) == 1
    kind, row_id, actor, now = dispatched[0]
    assert (kind, row_id, actor.kind, actor.role, now) == ("message", row.id, "agent", "admin", WORK)
    [card] = _cards(events)
    assert set(card) == SENT_CARD_KEYS | {"message_id"}
    assert card["kind"] == "outreach_sent" and card["message_id"] == row.id and card["schedule_id"] == sid
    assert (card["channel"], card["outcome"], card["message"]) == ("sms", "accepted", "보냈습니다")
    assert card["contact"] == {"id": who.id, "name": "김공정", "role_title": "공무", "company": "가람철근"}
    _no_phone(result.output)
    _no_phone(card)


async def test_delegated_call_is_queued_as_delegated(session, sid, tctx, events, fake_channel, dispatched):
    _conn(session)
    who = _person(session, sid)
    row = _call_draft(session, who, tctx.chat_session_id)
    result = await registry.call("notify.place_call", {"call_id": row.id}, tctx)
    assert result.ok, result.error
    assert result.output["outcome"] == "queued"
    row = _reread(session, row)
    assert (row.status, row.send_mode, row.origin, row.approved_by) == ("queued", "delegated", "agent", None)
    assert [(d.channel, d.row_id) for d in fake_channel.delivered] == [("call", row.id)]
    assert [(k, i) for k, i, *_ in dispatched] == [("call", row.id)]
    [card] = _cards(events)
    assert set(card) == SENT_CARD_KEYS | {"call_id"}
    assert (card["call_id"], card["channel"], card["outcome"]) == (row.id, "call", "queued")
    _no_phone(card)


async def test_tool_writes_nothing_to_its_session_before_the_gate(session, sid, tctx, fake_channel, monkeypatch):
    _conn(session)
    who = _person(session, sid)
    row = _draft(session, who, tctx.chat_session_id)
    real = gate.dispatch
    pending: list = []

    async def spy(kind, row_id, actor, *, now=None):
        pending.append((set(session.new), set(session.dirty), set(session.deleted)))
        return await real(kind, row_id, actor, now=now)

    monkeypatch.setattr(gate, "dispatch", spy)
    result = await registry.call("notify.send_message", {"message_id": row.id}, tctx)
    assert result.ok and pending == [(set(), set(), set())]


@pytest.mark.parametrize("case", ["test_mode", "daily", "person", "dnc", "off_hours", "unsure", "failed"])
async def test_delegated_send_still_blocked_by_test_mode_and_limits(session, sid, tctx, events, fake_channel,
                                                                   dispatched, monkeypatch, case):
    conn = _conn(session)
    who = _person(session, sid)
    if case == "test_mode":
        conn.test_mode, conn.allow_numbers_json = True, ["01000000288"]
    elif case in ("daily", "person"):
        conn.limits_json = {"daily_sms_total": 1} if case == "daily" else {"per_contact_sms_daily": 1}
        _draft(session, who, None, origin="user", origin_name="김공정", status="accepted", body="앞서 보낸 글",
               claimed_at=WORK.replace(hour=9))
    elif case == "dnc":
        who.do_not_contact = True
    elif case == "off_hours":
        monkeypatch.setattr(send_message, "_now", lambda: OFF)
    elif case == "unsure":
        fake_channel.result = Delivered("unsure")
    elif case == "failed":
        fake_channel.result = Delivered("failed", fail_code="network")
    session.commit()
    row = _draft(session, who, tctx.chat_session_id)
    result = await registry.call("notify.send_message", {"message_id": row.id}, tctx)
    assert result.ok, result.error  # 문이 막은 것도 도구는 돌았다 — 결과가 문의 판정이다
    want = {"test_mode": ("blocked_test", "blocked_test", None), "daily": ("limit_daily", "draft", None),
            "person": ("limit_person", "draft", None), "dnc": ("do_not_contact", "draft", None),
            "off_hours": ("scheduled", "scheduled", "delegated"), "unsure": ("unsure", "unconfirmed", "delegated"),
            "failed": ("failed", "failed", "delegated")}[case]
    row = _reread(session, row)
    assert (result.output["outcome"], row.status, row.send_mode) == want
    assert len(dispatched) == 1
    assert len(fake_channel.delivered) == (1 if case in ("unsure", "failed") else 0)
    [card] = _cards(events)
    assert (card["outcome"], card["message"]) == (result.output["outcome"], result.output["message"])
    if case == "unsure":  # 「확인 필요」는 보냄이 아니다 — 문의 글 그대로
        assert result.output["message"] == gate.UNSURE and "보냈습니다" not in json.dumps(result.output, ensure_ascii=False)
    if case == "off_hours":
        assert result.output["scheduled_at"] is not None
    else:
        assert result.output["scheduled_at"] is None


async def test_agent_without_delegation_is_refused_by_the_gate(session, sid, tctx, fake_channel, dispatched):
    """숨긴 도구를 그래도 부르면 문이 권한 차례에서 막는다 — 줄은 초안 그대로, 통로는 부르지 않는다."""
    _conn(session, agent_sms="approve", agent_kakao="approve", agent_call="approve")
    who = _person(session, sid)
    row = _draft(session, who, tctx.chat_session_id)
    call = _call_draft(session, who, tctx.chat_session_id)
    sent = await registry.call("notify.send_message", {"message_id": row.id}, tctx)
    placed = await registry.call("notify.place_call", {"call_id": call.id}, tctx)
    assert sent.output["outcome"] == placed.output["outcome"] == "needs_approval"
    assert _reread(session, row).status == "draft" and _reread(session, row).send_mode is None
    assert _reread(session, call).status == "draft"
    assert fake_channel.delivered == [] and len(dispatched) == 2


def _other_chat(session, admin_user) -> int:
    chat = chats.create_chat(session, user_id=admin_user.id)
    session.commit()
    return chat.id


@pytest.mark.parametrize("case", [
    "human_draft", "other_chat", "no_chat", "other_schedule", "missing", "accepted", "unconfirmed", "scheduled",
    "inbound", "inbound_draft", "sending",
])
async def test_agent_cannot_send_human_or_other_chat_draft(session, sid, tctx, events, admin_user, fake_channel,
                                                          dispatched, case):
    _conn(session)
    who = _person(session, sid)
    chat_id = tctx.chat_session_id
    over: dict = {
        "human_draft": {"origin": "user", "origin_name": "김공정"},
        "other_chat": {"chat_session_id": _other_chat(session, admin_user)},
        "no_chat": {"chat_session_id": None},
        "accepted": {"status": "accepted"},
        "unconfirmed": {"status": "unconfirmed"},
        "scheduled": {"status": "scheduled", "send_mode": "manual"},
        "inbound": {"direction": "in", "status": "received"},
        "inbound_draft": {"direction": "in"},  # 받은 줄은 상태가 무엇이든 보내지 않는다
        "sending": {"status": "sending"},
    }.get(case, {})
    target = who
    if case == "other_schedule":  # 다른 일정의 사람·초안 — 같은 대화 id 를 달고 있어도
        target = _person(session, schedules.store(session, schedules.sample()), number="01000000288")
    row = _draft(session, target, chat_id, **over)
    row_id = row.id + 1000 if case == "missing" else row.id
    before = (row.status, row.send_mode, row.chat_session_id)
    result = await registry.call("notify.send_message", {"message_id": row_id}, tctx)
    assert not result.ok and result.error == NOT_YOURS
    row = _reread(session, row)
    assert (row.status, row.send_mode, row.chat_session_id) == before
    assert dispatched == [] and fake_channel.delivered == [] and _cards(events) == []


@pytest.mark.parametrize("case", ["human_draft", "other_chat", "completed", "queued", "missing"])
async def test_agent_cannot_place_human_or_other_chat_call(session, sid, tctx, events, admin_user, fake_channel,
                                                          dispatched, case):
    _conn(session)
    who = _person(session, sid)
    over: dict = {
        "human_draft": {"origin": "user", "origin_name": "김공정"},
        "other_chat": {"chat_session_id": _other_chat(session, admin_user)},
        "completed": {"status": "completed"},
        "queued": {"status": "queued"},
    }.get(case, {})
    row = _call_draft(session, who, tctx.chat_session_id, **over)
    row_id = row.id + 1000 if case == "missing" else row.id
    result = await registry.call("notify.place_call", {"call_id": row_id}, tctx)
    assert not result.ok and result.error == NOT_YOURS
    assert dispatched == [] and fake_channel.delivered == [] and _cards(events) == []


async def test_outside_a_chat_nothing_can_be_sent(session, sid, admin_user, events, fake_channel, dispatched):
    """대화 밖에서(chat_session_id 없음) 부르면 대화 없는 초안도 보내지 않는다."""
    _conn(session)
    row = _draft(session, _person(session, sid), None)
    bare = ToolContext(session=session, user=admin_user, schedule_id=sid, emit=events.append)
    result = await registry.call("notify.send_message", {"message_id": row.id}, bare)
    assert not result.ok and result.error == NOT_YOURS and dispatched == [] and fake_channel.delivered == []


async def test_card_shows_the_channel_the_gate_used(session, sid, tctx, events, fake_channel):
    """카카오톡 초안이 문안 없이 문자로 나가면 카드의 channel 은 sms(문이 적은 대로)."""
    _conn(session)
    row = _draft(session, _person(session, sid), tctx.chat_session_id, channel="kakao")
    result = await registry.call("notify.send_message", {"message_id": row.id}, tctx)
    assert result.output["outcome"] == "accepted"
    assert _reread(session, row).channel == "sms"
    assert [c["channel"] for c in _cards(events)] == ["sms"]


async def test_call_blocked_by_hours_can_be_placed_again(session, sid, tctx, fake_channel, dispatched):
    """근무 밖에 막힌 통화(blocked_hours)는 같은 대화에서 다시 걸 수 있다 — 문이 처음부터 다시 본다."""
    _conn(session)
    who = _person(session, sid)
    row = _call_draft(session, who, tctx.chat_session_id, status="blocked_hours")
    result = await registry.call("notify.place_call", {"call_id": row.id}, tctx)
    assert result.ok and result.output["outcome"] == "queued" and len(dispatched) == 1


async def test_send_tools_refuse_field_and_take_no_schedule_argument(session, sid, chat_id, events, fake_channel,
                                                                   dispatched):
    _conn(session)
    who = _person(session, sid)
    row = _draft(session, who, chat_id)
    field = User(login_id="field1", name="박현장", role="field", password_hash="x")
    session.add(field)
    session.commit()
    fctx = ToolContext(session=session, user=field, schedule_id=sid, emit=events.append, chat_session_id=chat_id)
    result = await registry.call("notify.send_message", {"message_id": row.id}, fctx)
    assert not result.ok and result.error == FIELD_REFUSAL
    extra = await registry.call("notify.send_message", {"message_id": row.id, "schedule_id": sid}, fctx)
    assert not extra.ok and "입력 형식 오류" in extra.error
    assert dispatched == [] and fake_channel.delivered == []


async def test_one_call_dispatches_once_even_when_sent_twice(session, sid, tctx, fake_channel, dispatched):
    _conn(session)
    who = _person(session, sid)
    row = _draft(session, who, tctx.chat_session_id)
    first = await registry.call("notify.send_message", {"message_id": row.id}, tctx)
    again = await registry.call("notify.send_message", {"message_id": row.id}, tctx)
    assert first.output["outcome"] == "accepted"
    assert not again.ok and again.error == NOT_YOURS  # 이미 나간 줄은 없는 것과 같다 — 다시 보내지 않는다
    assert len(dispatched) == 1 and len(fake_channel.delivered) == 1


async def test_outreach_writes_no_evidence_rows(session, sid, tctx, fake_channel):
    _conn(session)
    who = _person(session, sid)
    row = _draft(session, who, tctx.chat_session_id)
    call = _call_draft(session, who, tctx.chat_session_id)
    await registry.call("notify.send_message", {"message_id": row.id}, tctx)
    await registry.call("notify.place_call", {"call_id": call.id}, tctx)
    session.expire_all()
    for model in (EvidenceSearch, EvidenceItem, EvidenceLink):
        assert session.scalar(select(func.count()).select_from(model)) == 0
