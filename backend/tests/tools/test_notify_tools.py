"""대화 에이전트 연락 도구(계획 4 Task 80): contacts.list · notify.draft_message · notify.draft_call · notify.status.

사람이 대화 창에서 시키는 길이다. 도구는 초안만 만들고 아무것도 보내지 않는다(나가는 문을 부르지 않음).
지키는 것: 결과·카드에 전화번호가 없다(가린 꼴도) · 메모·수신 거부 까닭은 싣지 않는다 · 지금 일정의 주소록만
(다른 일정의 id 는 없는 것과 같다) · 일정 id 는 인자로 받지 않는다 · 현장 관리자는 쓸 수 없다.
"""

import json
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.outreach import hours, phone
from app.outreach.harness import gate
from app.store import chats, outreach
from app.store.tables import User
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    ContactReport,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
    VoiceSettings,
)
from app.tools import registry
from app.tools.context import ToolContext
from app.tools.notify import list_contacts
from tests import schedules
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY, SENTINEL_PHONE

KST = hours.KST
WORK = datetime(2026, 11, 27, 10, 0, tzinfo=KST)  # 금요일 10시 — 근무 중
OFF = datetime(2026, 11, 27, 19, 0, tzinfo=KST)  # 금요일 19시 — 근무 밖
OTHER_COMPANY = "비밀협력사"  # 다른 프로젝트에만 있는 이름
OTHER_PERSON = "남의담당"
MOBILE2 = "01000000288"  # 가상 휴대전화 둘째
LANDLINE = phone.normalize("02-2345-0177")
REP = phone.normalize("1588-0166")
FIELD_REFUSAL = "현장 관리자는 연락처를 쓸 수 없습니다."
NOT_FOUND = "연락처를 찾을 수 없습니다."
KAKAO_REFUSAL = "카카오톡은 채널·문안 승인 뒤 쓸 수 있습니다 — 문자로 초안을 만드세요."
TOOLS = ("contacts.list", "notify.draft_message", "notify.draft_call", "notify.status")
ITEM_KEYS = {"contact_id", "name", "role_title", "company", "trade", "channels", "has_phone", "working_now", "language",
             "do_not_contact"}
CARD_KEYS = {"kind", "schedule_id", "message_id", "contact", "channel", "body", "body_ko", "needs_approval"}
CALL_CARD_KEYS = {"kind", "schedule_id", "call_id", "contact", "purpose", "questions", "avoid", "language",
                  "needs_approval"}


@pytest.fixture(autouse=True)
def at_work(monkeypatch):
    monkeypatch.setattr(list_contacts, "_now", lambda: WORK)


@pytest.fixture(autouse=True)
def gate_never_called(monkeypatch):
    """초안 도구는 문을 부르지 않는다 — 부르면 시험이 실패한다."""

    async def boom(*_args, **_kwargs):
        raise AssertionError("초안 도구가 나가는 문을 불렀습니다")

    monkeypatch.setattr(gate, "dispatch", boom)


@pytest.fixture
def sid2(session) -> int:
    return schedules.store(session, schedules.sample())


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
    values = {"name": "시험 연결", "base_url": "https://kat.invalid", "secret_ciphertext": SENTINEL_KEY,
              "secret_last4": "9999", "account_id": "acct-test-0001", "sender_number": SENTINEL_DIGITS,
              "allow_numbers_json": [SENTINEL_DIGITS], "handoff_number": SENTINEL_DIGITS, "is_default": True,
              "status": "ok", "test_mode": True, **over}
    row = NotifyConnection(**values)
    session.add(row)
    session.commit()
    return row


def _person(session, sid: int, *, name: str = "김공정", company: str = "가람철근", trade: str = "철근",
            number: str | None = SENTINEL_DIGITS, **over) -> Contact:
    firm = ContactCompany(schedule_id=sid, name=company, trade=trade)
    session.add(firm)
    session.flush()
    can = {"can_sms": phone.can_sms(number), "can_kakao": phone.can_sms(number), "can_call": phone.can_call(number)}
    who = Contact(**{"schedule_id": sid, "company_id": firm.id, "name": name, "role_title": "공무", "phone": number,
                     **can, **over})
    session.add(who)
    session.commit()
    return who


async def _call(name: str, args: dict, ctx: ToolContext):
    return await registry.call(name, args, ctx)


def _count(session, model) -> int:
    session.expire_all()
    return session.scalar(select(func.count()).select_from(model))


def _digits(value: object) -> str:
    return "".join(ch for ch in json.dumps(value, ensure_ascii=False, default=str) if ch.isdigit())


def _no_phone(value: object) -> None:
    digits = _digits(value)
    assert SENTINEL_DIGITS not in digits and SENTINEL_DIGITS[1:] not in digits
    text = json.dumps(value, ensure_ascii=False, default=str)
    assert SENTINEL_KEY not in text and "acct-test-0001" not in text and "****" not in text


def _cards(events: list) -> list[dict]:
    return [e.data for e in events if e.type == "card"]


# ── 등록 ────────────────────────────────────────────────────────────────


def test_tools_are_registered_under_the_contacts_program():
    specs = {s.name: s for s in registry.list_tools(enabled_only=False)}
    assert set(TOOLS) <= set(specs)
    assert {name: (specs[name].program, specs[name].mutates) for name in TOOLS} == {
        "contacts.list": ("contacts", False), "notify.draft_message": ("contacts", True),
        "notify.draft_call": ("contacts", True), "notify.status": ("contacts", False)}


@pytest.mark.parametrize("name, args", [
    ("contacts.list", {}),
    ("notify.draft_message", {"contact_id": 1, "channel": "sms", "body": "안녕하세요"}),
    ("notify.draft_call", {"contact_id": 1, "purpose": "타설 확인", "questions": ["내일 가능하신가요?"]}),
    ("notify.status", {}),
])
async def test_input_models_forbid_extra(tctx, session, name, args):
    """일정 id 는 인자로 받지 않는다 — 넣으면 입력 형식 오류(도구는 돌지 않음)."""
    result = await _call(name, {**args, "schedule_id": 1}, tctx)
    assert not result.ok and result.error.startswith("입력 형식 오류")
    assert _count(session, OutreachMessage) == 0 and _count(session, OutreachCall) == 0


# ── contacts.list ───────────────────────────────────────────────────────


async def test_list_is_project_scoped(session, sid, sid2, tctx):
    mine = _person(session, sid)
    _person(session, sid2, name=OTHER_PERSON, company=OTHER_COMPANY, number=MOBILE2)
    result = await _call("contacts.list", {}, tctx)
    assert result.ok, result.error
    assert result.output["total"] == 1 and [i["contact_id"] for i in result.output["items"]] == [mine.id]
    text = json.dumps(result.output, ensure_ascii=False)
    assert OTHER_PERSON not in text and OTHER_COMPANY not in text
    found = await _call("contacts.list", {"query": "남의"}, tctx)
    assert found.ok and found.output == {"total": 0, "items": []}


async def test_list_item_shape_and_values(session, sid, sid2, tctx, monkeypatch):
    kim = _person(session, sid, language="vi")
    lee = _person(session, sid, name="이전기", company="한빛전기", trade="전기", number=None)
    park = _person(session, sid, name="박유선", company="가람철근", trade="철근", number=LANDLINE)
    hidden = _person(session, sid, name="숨은사람", number=MOBILE2, hidden=True)
    # 다른 프로젝트에서 이 번호를 수신 거부로 표시 → 이 프로젝트의 박유선도 수신 거부(번호 기준)
    outreach.mark_do_not_contact(session, LANDLINE, reason="그만")
    session.commit()
    result = await _call("contacts.list", {}, tctx)
    assert result.ok, result.error
    items = {i["contact_id"]: i for i in result.output["items"]}
    assert set(items) == {kim.id, lee.id, park.id} and hidden.id not in items and result.output["total"] == 3
    assert all(set(i) == ITEM_KEYS for i in items.values())
    assert items[kim.id] == {"contact_id": kim.id, "name": "김공정", "role_title": "공무", "company": "가람철근",
                             "trade": "철근", "channels": ["sms", "kakao", "call"], "has_phone": True,
                             "working_now": True, "language": "vi", "do_not_contact": False}
    assert items[lee.id]["channels"] == [] and items[lee.id]["has_phone"] is False
    assert items[park.id]["channels"] == ["call"] and items[park.id]["do_not_contact"] is True
    stale = _person(session, sid, name="깃발만", number=LANDLINE, can_sms=True, can_kakao=True)  # 깃발이 남은 유선
    again = await _call("contacts.list", {"query": "깃발만"}, tctx)
    assert [i["channels"] for i in again.output["items"]] == [["call"]] and stale.can_sms
    monkeypatch.setattr(list_contacts, "_now", lambda: OFF)
    later = await _call("contacts.list", {"query": "김공"}, tctx)
    assert [i["working_now"] for i in later.output["items"]] == [False]


async def test_list_finds_by_company_or_trade_and_limits(session, sid, tctx):
    for n in range(3):
        _person(session, sid, name=f"철근{n}", company="가람철근", trade="철근", number=None)
    _person(session, sid, name="이전기", company="한빛전기", trade="전기", number=None)
    by_firm = await _call("contacts.list", {"query": "한빛"}, tctx)
    assert [i["name"] for i in by_firm.output["items"]] == ["이전기"]
    by_trade = await _call("contacts.list", {"query": "철근", "limit": 2}, tctx)
    assert by_trade.output["total"] == 3 and len(by_trade.output["items"]) == 2
    too_many = await _call("contacts.list", {"limit": 21}, tctx)
    assert not too_many.ok and too_many.error.startswith("입력 형식 오류")


# ── notify.draft_message ────────────────────────────────────────────────


async def test_draft_message_makes_agent_draft_and_card(session, sid, tctx, events, chat_id, fake_channel):
    _conn(session)
    who = _person(session, sid)
    result = await _call("notify.draft_message", {"contact_id": who.id, "channel": "sms", "body": " 내일 3층 타설 가능하신가요? ",
                                                  "activity_id": "A"}, tctx)
    assert result.ok, result.error
    assert set(result.output) == {"message_id", "status", "needs_approval", "note"}
    assert result.output["status"] == "draft" and result.output["needs_approval"] is True
    assert "보내지 않았" in result.output["note"] and "[보내기]를 눌러야" in result.output["note"]
    session.commit()
    row = session.get(OutreachMessage, result.output["message_id"])
    assert (row.origin, row.origin_name, row.status, row.direction, row.channel, row.kind) == (
        "agent", "에이전트", "draft", "out", "sms", "normal")
    assert row.schedule_id == sid and row.contact_id == who.id and row.chat_session_id == chat_id
    assert row.body == "내일 3층 타설 가능하신가요?" and row.activity_id == "A"
    assert row.send_mode is None and row.approved_by is None and row.peer_number is None
    [card] = _cards(events)
    assert set(card) == CARD_KEYS
    assert card == {"kind": "outreach_draft", "schedule_id": sid, "message_id": row.id,
                    "contact": {"id": who.id, "name": "김공정", "role_title": "공무", "company": "가람철근"},
                    "channel": "sms", "body": row.body, "body_ko": None, "needs_approval": True}
    assert fake_channel.delivered == []


async def test_draft_under_delegation_is_still_only_a_draft(session, sid, tctx, events, fake_channel):
    _conn(session, agent_sms="delegate", agent_call="delegate")
    who = _person(session, sid, language="vi")
    result = await _call("notify.draft_message", {"contact_id": who.id, "channel": "sms", "body": "Xin chào",
                                                  "body_ko": "안녕하세요"}, tctx)
    assert result.ok, result.error
    assert result.output["needs_approval"] is False and "보내지 않았" in result.output["note"]
    assert "다시" in result.output["note"] and "눌러야" not in result.output["note"]  # 보낼 때 문이 다시 본다
    row = session.get(OutreachMessage, result.output["message_id"])
    assert (row.status, row.send_mode, row.body_ko) == ("draft", None, "안녕하세요")
    assert _cards(events)[0]["needs_approval"] is False and _cards(events)[0]["body_ko"] == "안녕하세요"
    call = await _call("notify.draft_call", {"contact_id": who.id, "purpose": "타설 확인", "questions": ["가능?"]}, tctx)
    assert call.ok and call.output["needs_approval"] is False
    assert session.get(OutreachCall, call.output["call_id"]).send_mode is None
    assert fake_channel.delivered == []


async def test_needs_approval_follows_each_channel(session, sid, tctx):
    _conn(session, agent_call="delegate")  # 문자는 승인 받기, 전화만 위임
    who = _person(session, sid)
    text = await _call("notify.draft_message", {"contact_id": who.id, "channel": "sms", "body": "안녕"}, tctx)
    call = await _call("notify.draft_call", {"contact_id": who.id, "purpose": "확인", "questions": ["가능?"]}, tctx)
    assert (text.output["needs_approval"], call.output["needs_approval"]) == (True, False)
    assert "[전화 걸기]를 눌러야" not in call.output["note"]


async def test_draft_without_connection_needs_approval(session, sid, tctx):
    who = _person(session, sid)
    result = await _call("notify.draft_message", {"contact_id": who.id, "channel": "sms", "body": "안녕하세요"}, tctx)
    assert result.ok and result.output["needs_approval"] is True
    assert "알림 연결" in result.output["note"]


@pytest.mark.parametrize("tool, args", [
    ("notify.draft_message", {"channel": "sms", "body": "안녕하세요"}),
    ("notify.draft_call", {"purpose": "타설 확인", "questions": ["가능?"]}),
])
async def test_draft_for_other_project_contact_is_refused(session, sid, sid2, tctx, events, tool, args):
    other = _person(session, sid2, name=OTHER_PERSON, company=OTHER_COMPANY)
    result = await _call(tool, {"contact_id": other.id, **args}, tctx)
    assert not result.ok and result.error == NOT_FOUND
    missing = await _call(tool, {"contact_id": 9999, **args}, tctx)
    assert not missing.ok and missing.error == NOT_FOUND
    assert _count(session, OutreachMessage) == 0 and _count(session, OutreachCall) == 0 and events == []


@pytest.mark.parametrize("tool, args", [
    ("notify.draft_message", {"channel": "sms", "body": "안녕하세요"}),
    ("notify.draft_call", {"purpose": "타설 확인", "questions": ["가능?"]}),
])
@pytest.mark.parametrize("case", ["flag", "flag_no_phone", "number", "no_phone", "invalid"])
async def test_draft_refused_for_dnc_or_no_phone(session, sid, sid2, tctx, events, tool, args, case):
    over = {"flag": {"do_not_contact": True, "dnc_reason": f"본인 요청 {SENTINEL_PHONE}"},
            "flag_no_phone": {"do_not_contact": True, "number": None},
            "number": {}, "no_phone": {"number": None}, "invalid": {"phone_invalid": True}}[case]
    who = _person(session, sid, **over)
    if case == "number":  # 다른 프로젝트에서 같은 번호를 수신 거부 → 이 프로젝트에서도 막힘
        _person(session, sid2, name=OTHER_PERSON, company=OTHER_COMPANY)
        outreach.mark_do_not_contact(session, SENTINEL_DIGITS, reason=f"{SENTINEL_PHONE} 그만")
        session.commit()
    result = await _call(tool, {"contact_id": who.id, **args}, tctx)
    assert not result.ok
    assert ("수신 거부" in result.error) if case.startswith("flag") or case == "number" else ("번호" in result.error)
    _no_phone(result.error)
    assert OTHER_COMPANY not in result.error and "본인 요청" not in result.error and "그만" not in result.error
    assert _count(session, OutreachMessage) == 0 and _count(session, OutreachCall) == 0 and events == []


@pytest.mark.parametrize("number", [LANDLINE, REP])
async def test_sms_draft_refused_for_landline(session, sid, tctx, events, number):
    who = _person(session, sid, number=number)
    for channel in ("sms", "kakao"):
        result = await _call("notify.draft_message", {"contact_id": who.id, "channel": channel, "body": "안녕"}, tctx)
        assert not result.ok and "문자" in result.error
    assert _count(session, OutreachMessage) == 0 and events == []
    call = await _call("notify.draft_call", {"contact_id": who.id, "purpose": "확인", "questions": ["가능?"]}, tctx)
    assert call.ok, call.error


async def test_sms_draft_refused_for_landline_with_a_stale_flag(session, sid, tctx):
    who = _person(session, sid, number=LANDLINE, can_sms=True, can_kakao=True)
    result = await _call("notify.draft_message", {"contact_id": who.id, "channel": "sms", "body": "안녕"}, tctx)
    assert not result.ok and "문자" in result.error
    assert _count(session, OutreachMessage) == 0


async def test_sms_draft_refused_when_texting_is_turned_off(session, sid, tctx):
    who = _person(session, sid, can_sms=False)
    result = await _call("notify.draft_message", {"contact_id": who.id, "channel": "sms", "body": "안녕"}, tctx)
    assert not result.ok and "문자" in result.error
    nocall = _person(session, sid, name="통화안됨", can_call=False)
    call = await _call("notify.draft_call", {"contact_id": nocall.id, "purpose": "확인", "questions": ["가능?"]}, tctx)
    assert not call.ok and "전화" in call.error
    assert _count(session, OutreachMessage) == 0 and _count(session, OutreachCall) == 0


async def test_kakao_draft_is_refused_while_the_channel_is_not_registered(session, sid, tctx, events):
    _conn(session)
    who = _person(session, sid)
    result = await _call("notify.draft_message", {"contact_id": who.id, "channel": "kakao", "template_use": "schedule",
                                                  "template_vars": {"날짜": "3월 2일"}}, tctx)
    assert not result.ok and result.error == KAKAO_REFUSAL
    assert _count(session, OutreachMessage) == 0 and events == []


@pytest.mark.parametrize("args, part", [
    ({"body": None}, "body"),
    ({"body": "안녕", "template_use": "schedule"}, "문안"),
    ({"body": "안녕", "template_vars": {"날짜": "3월 2일"}}, "문안"),
    ({"body": "안녕\u202e하세요"}, "보이지 않는"),
    ({"body": "안녕", "body_ko": "안\u200b녕"}, "보이지 않는"),
    ({"body": "안녕", "activity_id": "ZZ"}, "작업"),
])
async def test_bad_message_drafts_are_refused_without_a_row(session, sid, tctx, events, args, part):
    who = _person(session, sid)
    result = await _call("notify.draft_message", {"contact_id": who.id, "channel": "sms", **args}, tctx)
    assert not result.ok and part in result.error
    assert _count(session, OutreachMessage) == 0 and events == []


@pytest.mark.parametrize("args, ok", [
    ({"body": ""}, False), ({"body": "가" * 1001}, False), ({"body": "가" * 1000}, True),
])
async def test_message_body_length(session, sid, tctx, args, ok):
    who = _person(session, sid)
    result = await _call("notify.draft_message", {"contact_id": who.id, "channel": "sms", **args}, tctx)
    assert result.ok is ok


# ── notify.draft_call ───────────────────────────────────────────────────


async def test_draft_call_makes_agent_draft_and_card(session, sid, tctx, events, chat_id):
    _conn(session)
    who = _person(session, sid, language="en")
    args = {"contact_id": who.id, "purpose": "3층 타설 일정 확인", "questions": ["내일 가능하신가요?", "인원은 몇 명인가요?"],
            "avoid": ["금액"], "activity_id": "B"}
    result = await _call("notify.draft_call", args, tctx)
    assert result.ok, result.error
    assert set(result.output) == {"call_id", "status", "language", "needs_approval", "note"}
    assert (result.output["status"], result.output["language"], result.output["needs_approval"]) == ("draft", "en", True)
    assert "걸지 않았" in result.output["note"] and "[전화 걸기]" in result.output["note"]
    assert "AI 전화" in result.output["note"]  # 음성 설정이 아직 없음
    row = session.get(OutreachCall, result.output["call_id"])
    assert (row.origin, row.origin_name, row.status, row.direction, row.language) == ("agent", "에이전트", "draft", "out", "en")
    assert row.schedule_id == sid and row.contact_id == who.id and row.chat_session_id == chat_id
    assert (row.purpose, row.questions_json, row.avoid_json, row.activity_id) == (
        "3층 타설 일정 확인", ["내일 가능하신가요?", "인원은 몇 명인가요?"], ["금액"], "B")
    assert row.send_mode is None and row.approved_by is None and row.peer_number is None
    [card] = _cards(events)
    assert set(card) == CALL_CARD_KEYS
    assert card == {"kind": "outreach_call_draft", "schedule_id": sid, "call_id": row.id,
                    "contact": {"id": who.id, "name": "김공정", "role_title": "공무", "company": "가람철근"},
                    "purpose": row.purpose, "questions": row.questions_json, "avoid": ["금액"], "language": "en",
                    "needs_approval": True}


async def test_draft_call_note_has_no_setup_line_when_voice_is_ready(session, sid, tctx):
    conn = _conn(session)
    session.add(VoiceSettings(connection_id=conn.id, status="ok", agent_number="07000000001"))
    session.commit()
    who = _person(session, sid)
    result = await _call("notify.draft_call", {"contact_id": who.id, "purpose": "확인", "questions": ["가능?"]}, tctx)
    assert result.ok and "AI 전화" not in result.output["note"]


@pytest.mark.parametrize("args", [
    {"purpose": "", "questions": ["가능?"]}, {"purpose": "가" * 201, "questions": ["가능?"]},
    {"purpose": "확인", "questions": []}, {"purpose": "확인", "questions": ["1", "2", "3", "4", "5", "6"]},
    {"purpose": "확인", "questions": ["가능?"], "avoid": ["1", "2", "3", "4", "5", "6"]},
    {"purpose": "확\u202e인", "questions": ["가능?"]}, {"purpose": "확인", "questions": ["가\u0007능?"]},
    {"purpose": "확인", "questions": ["가능?"], "activity_id": "ZZ"},
])
async def test_bad_call_drafts_are_refused_without_a_row(session, sid, tctx, events, args):
    who = _person(session, sid)
    result = await _call("notify.draft_call", {"contact_id": who.id, **args}, tctx)
    assert not result.ok
    assert _count(session, OutreachCall) == 0 and events == []


@pytest.mark.parametrize("form", [SENTINEL_PHONE, "+82 10-0000-0199", "(010)0000-0199", "０１０-００００-０１９９"])
@pytest.mark.parametrize("field", ["purpose", "questions", "avoid"])
async def test_call_draft_with_a_phone_number_is_refused_like_the_call_api(session, sid, tctx, events, field, form):
    """사람이 가린 글을 승인하는 동안 음성 에이전트가 번호를 받는 일이 없게 — 통화 API 와 같은 has_phone 검사·같은 글."""
    who = _person(session, sid)
    args = {"purpose": "확인", "questions": ["가능?"], "avoid": []}
    text = f"{form} 로 회신"
    args[field] = text if field == "purpose" else [text]
    result = await _call("notify.draft_call", {"contact_id": who.id, **args}, tctx)
    assert not result.ok
    assert result.error == "전화번호는 넣을 수 없습니다 — 연락처에서 고릅니다"
    assert _count(session, OutreachCall) == 0 and events == []


# ── notify.status ───────────────────────────────────────────────────────


def _message(session, sid, contact_id, **over) -> OutreachMessage:
    row = OutreachMessage(**{"schedule_id": sid, "contact_id": contact_id, "direction": "out", "channel": "sms",
                             "origin": "user", "origin_name": "일반 사용자", "body": "안녕하세요", **over})
    session.add(row)
    session.commit()
    return row


async def test_status_hides_numbers_in_replies(session, sid, sid2, tctx):
    who = _person(session, sid)
    other = _person(session, sid, name="이전기", company="한빛전기", trade="전기", number=MOBILE2)
    sent = _message(session, sid, who.id, status="accepted")
    reply = _message(session, sid, who.id, direction="in", origin="peer", status="received",
                     body=f"제 번호 {SENTINEL_PHONE} 로 다시 주세요 공일공 영영영영 영일구구 " + "가" * 300)
    unsure = _message(session, sid, other.id, status="unconfirmed")
    stranger = _person(session, sid2, name=OTHER_PERSON, company=OTHER_COMPANY, number=MOBILE2)
    _message(session, sid2, stranger.id, body=OTHER_COMPANY)
    call = OutreachCall(schedule_id=sid, contact_id=who.id, origin="agent", status="completed",
                        summary_ko=f"상대가 {SENTINEL_PHONE} 로 회신 요청. " + "나" * 300)
    session.add_all([call, OutreachCall(schedule_id=sid2, contact_id=stranger.id, origin="agent", summary_ko=OTHER_COMPANY)])
    session.add_all([ContactReport(schedule_id=sid, medium="sms", contact_id=who.id, kind="delay", status="open"),
                     ContactReport(schedule_id=sid, medium="sms", contact_id=other.id, kind="delay", status="open"),
                     ContactReport(schedule_id=sid, medium="sms", contact_id=who.id, kind="delay", status="reviewed"),
                     ContactReport(schedule_id=sid2, medium="sms", contact_id=stranger.id, kind="delay", status="open")])
    session.commit()

    result = await _call("notify.status", {}, tctx)
    assert result.ok, result.error
    out = result.output
    assert set(out) == {"messages", "calls", "reports_open"} and out["reports_open"] == 2
    assert [m["id"] for m in out["messages"]] == [unsure.id, reply.id, sent.id]  # 최근 것부터, 이 일정만
    assert set(out["messages"][0]) == {"id", "contact_id", "direction", "channel", "status", "at", "text"}
    shown = {m["id"]: m for m in out["messages"]}
    assert shown[unsure.id]["status"] == "unconfirmed" and shown[reply.id]["direction"] == "in"
    assert "[번호]" in shown[reply.id]["text"] and len(shown[reply.id]["text"]) <= 200
    assert [c["id"] for c in out["calls"]] == [call.id] and len(out["calls"][0]["summary"]) <= 200
    assert set(out["calls"][0]) == {"id", "contact_id", "direction", "status", "at", "summary"}
    assert "[번호]" in out["calls"][0]["summary"]
    _no_phone(out)
    assert OTHER_COMPANY not in json.dumps(out, ensure_ascii=False)

    one = await _call("notify.status", {"contact_id": who.id, "limit": 1}, tctx)
    assert [m["id"] for m in one.output["messages"]] == [reply.id] and one.output["reports_open"] == 1
    elsewhere = await _call("notify.status", {"contact_id": stranger.id}, tctx)
    assert not elsewhere.ok and elsewhere.error == NOT_FOUND
    too_many = await _call("notify.status", {"limit": 11}, tctx)
    assert not too_many.ok


# ── 역할·일정 없음 ───────────────────────────────────────────────────────


@pytest.mark.parametrize("name, args", [
    ("contacts.list", {}), ("notify.status", {}),
    ("notify.draft_message", {"channel": "sms", "body": "안녕하세요"}),
    ("notify.draft_call", {"purpose": "타설 확인", "questions": ["가능?"]}),
])
async def test_field_role_is_refused(session, sid, events, name, args):
    who = _person(session, sid)
    field = User(login_id="site1", name="박현장", role="field", password_hash="x")
    session.add(field)
    session.commit()
    ctx = ToolContext(session=session, user=field, schedule_id=sid, emit=events.append)
    if name.startswith("notify.draft"):
        args = {"contact_id": who.id, **args}
    result = await _call(name, args, ctx)
    assert not result.ok and result.error == FIELD_REFUSAL
    assert _count(session, OutreachMessage) == 0 and _count(session, OutreachCall) == 0 and events == []


async def test_tools_need_a_target_schedule(session, admin_user, events):
    ctx = ToolContext(session=session, user=admin_user, schedule_id=None, emit=events.append)
    result = await _call("contacts.list", {}, ctx)
    assert not result.ok and result.error == "대상 일정이 없습니다."


# ── 번호·메모가 모델에 가지 않는다 ─────────────────────────────────────────


async def test_notes_and_reasons_are_hidden_before_model(session, sid, tctx, events):
    _conn(session)
    who = _person(session, sid, note=f"개인 번호 {SENTINEL_PHONE} · 공일공 영영영영 영일구구")
    refused = _person(session, sid, name="거부한분", do_not_contact=True,
                      dnc_reason=f"{SENTINEL_PHONE} 로 그만 보내래요", note=f"{SENTINEL_PHONE}")
    outputs = [await _call("contacts.list", {}, tctx),
               await _call("notify.draft_message", {"contact_id": who.id, "channel": "sms", "body": "안녕"}, tctx),
               await _call("notify.draft_call", {"contact_id": who.id, "purpose": "확인", "questions": ["가능?"]}, tctx),
               await _call("notify.draft_message", {"contact_id": refused.id, "channel": "sms", "body": "안녕"}, tctx),
               await _call("notify.draft_call", {"contact_id": refused.id, "purpose": "확인", "questions": ["가"]}, tctx),
               await _call("notify.status", {"contact_id": refused.id}, tctx)]
    seen = [r.output if r.ok else r.error for r in outputs] + _cards(events)
    _no_phone(seen)
    text = json.dumps(seen, ensure_ascii=False)
    assert "개인 번호" not in text and "그만 보내래요" not in text and "공일공" not in text


async def test_no_tool_output_or_card_contains_phone(session, sid, tctx, events):
    """도구 넷의 결과·카드 어디에도 SENTINEL_PHONE 의 숫자가 없다(어느 꼴이든). 가린 꼴(****)도 없다."""
    _conn(session, agent_sms="delegate")
    who = _person(session, sid, name=f"김공정 {SENTINEL_PHONE}", role_title=f"공무 {SENTINEL_PHONE}",
                  company=f"가람 {SENTINEL_PHONE}", trade=f"철근 {SENTINEL_PHONE}", note=SENTINEL_PHONE)
    _message(session, sid, who.id, direction="in", origin="peer", status="received", body=f"회신 {SENTINEL_PHONE}")
    session.add(OutreachCall(schedule_id=sid, contact_id=who.id, origin="agent", status="completed",
                             summary_ko=f"요약 {SENTINEL_PHONE}"))
    session.commit()
    results = [await _call("contacts.list", {"query": "김공정"}, tctx),
               await _call("notify.draft_message", {"contact_id": who.id, "channel": "sms", "body": "안녕"}, tctx),
               await _call("notify.draft_call", {"contact_id": who.id, "purpose": "확인", "questions": ["가능?"]}, tctx),
               await _call("notify.status", {"contact_id": who.id}, tctx)]
    assert all(r.ok for r in results), [r.error for r in results]
    assert len(_cards(events)) == 2
    _no_phone([r.output for r in results] + [e.data for e in events])


# ── 카카오톡 통로가 등록된 뒤(Task 101) ──────────────────────────────────


def _template(session, conn: NotifyConnection, use: str, status: str = "approved") -> int:
    from app.store.tables_outreach import KakaoTemplate

    row = KakaoTemplate(connection_id=conn.id, channel="@시험", provider_template_id=f"T-{use}-{status}", use=use,
                        body="#{날짜} 작업 확인 부탁드립니다", status=status)
    session.add(row)
    session.commit()
    return row.id


async def test_kakao_draft_uses_an_approved_template_once_the_channel_is_registered(session, sid, tctx, events,
                                                                                   fake_channel):
    conn = _conn(session)
    _template(session, conn, "schedule", status="reviewing")
    approved = _template(session, conn, "schedule")
    who = _person(session, sid)
    args = {"contact_id": who.id, "channel": "kakao", "body": "3월 2일 작업 확인 부탁드립니다", "template_use": "schedule",
            "template_vars": {"날짜": "3월 2일"}}
    result = await _call("notify.draft_message", args, tctx)
    assert result.ok, result.error
    row = session.get(OutreachMessage, result.output["message_id"])
    assert (row.channel, row.template_id, row.template_vars_json, row.status, row.origin) == (
        "kakao", approved, {"날짜": "3월 2일"}, "draft", "agent")
    assert _cards(events)[0]["channel"] == "kakao" and fake_channel.delivered == []
    missing = await _call("notify.draft_message", {**args, "template_use": "other"}, tctx)
    assert not missing.ok and "문안" in missing.error
    off = _person(session, sid, name="카톡끔", can_kakao=False)
    refused = await _call("notify.draft_message", {**args, "contact_id": off.id}, tctx)
    assert not refused.ok and "카카오톡" in refused.error
    wired = _person(session, sid, name="유선", number=LANDLINE)
    landline = await _call("notify.draft_message", {**args, "contact_id": wired.id}, tctx)
    assert not landline.ok and "문자" in landline.error
    assert _count(session, OutreachMessage) == 1


@pytest.mark.parametrize("value", ["3월\u202e 2일", "3월\u200b2일", "3월\u0007 2일"])
async def test_template_values_are_checked_for_hidden_characters(session, sid, tctx, events, fake_channel, value):
    """문안 빈칸 값도 본문과 같은 글자 검사(메시지 API 의 check_body 와 같은 범위)."""
    conn = _conn(session)
    _template(session, conn, "schedule")
    who = _person(session, sid)
    result = await _call("notify.draft_message", {"contact_id": who.id, "channel": "kakao", "body": "작업 확인 부탁드립니다",
                                                  "template_use": "schedule", "template_vars": {"날짜": value}}, tctx)
    assert not result.ok and "보이지 않는" in result.error
    assert _count(session, OutreachMessage) == 0 and events == []


# ── 공용 초안 함수·하나의 연락 가능 검사(후속) ──────────────────────────────


def _spy(monkeypatch, module, name: str) -> list:
    calls, real = [], getattr(module, name)

    def wrapped(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapped)
    return calls


async def test_message_draft_is_made_by_the_shared_agent_draft_function(session, sid, tctx, events, fake_channel,
                                                                        monkeypatch):
    from app.programs.outreach import service

    conn = _conn(session)
    _template(session, conn, "schedule")
    who = _person(session, sid)
    made = _spy(monkeypatch, service, "create_agent_draft")
    ok = await _call("notify.draft_message", {"contact_id": who.id, "channel": "sms", "body": "안녕"}, tctx)
    assert ok.ok and len(made) == 1 and made[0][1]["chat_session_id"] == tctx.chat_session_id
    bad = await _call("notify.draft_message", {"contact_id": who.id, "channel": "kakao", "body": "작업 확인 부탁드립니다",
                                               "template_use": "schedule", "template_vars": {"날짜": "3월\u202e 2일"}}, tctx)
    assert not bad.ok and "보이지 않는" in bad.error and len(made) == 2  # 공용 함수가 문안 값을 보고 거절
    assert _count(session, OutreachMessage) == 1 and len(_cards(events)) == 1


async def test_call_draft_refuses_do_not_contact_through_the_shared_check(session, sid, sid2, tctx, events,
                                                                         monkeypatch):
    from app.programs.outreach import service

    who = _person(session, sid)
    _person(session, sid2, name=OTHER_PERSON, company=OTHER_COMPANY)
    outreach.mark_do_not_contact(session, SENTINEL_DIGITS, reason="그만")
    session.commit()
    checked = _spy(monkeypatch, service, "check_reachable")
    result = await _call("notify.draft_call", {"contact_id": who.id, "purpose": "확인", "questions": ["가능?"]}, tctx)
    assert not result.ok and result.error == "이 사람은 수신 거부라 연락 초안을 만들 수 없습니다."
    assert [c[0][1:] for c in checked] == [(sid, who.id, "call")]
    assert _count(session, OutreachCall) == 0 and events == []
