"""나가는 문(Task 65) — 보내기·걸기 한 함수의 흐름: 차례, 통로 결과, 동시성, 잠금, 사건 수, 새지 않는 것.

차례마다의 자세한 규칙은 test_gate_rules.py, 답·자동 답·받지 않은 전화는 test_gate_replies.py.
번호·키는 모두 가상이다(이름표의 SENTINEL_PHONE·SENTINEL_KEY). 아래 도우미는 세 파일이 같이 쓴다.
"""

import ast
import asyncio
import inspect
import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import get_args

import pytest
from sqlalchemy import create_engine

import app
from app import db
from app.config import Settings
from app.outreach import hours, redact
from app.outreach.harness import events, gate
from app.outreach.harness.types import (
    GATE_NOTES,
    GATE_RULES,
    Actor,
    Delivered,
    OutcomeCode,
    Ref,
)
from app.store import outreach
from app.store.tables_outreach import (
    BlockedNumber,
    Contact,
    ContactCompany,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
)
from app.store.timeutil import as_utc
from tests.outreach_doubles import (
    SENTINEL_DIGITS,
    SENTINEL_KEY,
    SENTINEL_PHONE,
    assert_clean,
)

KST = hours.KST
WORK = datetime(2026, 11, 27, 10, 0, tzinfo=KST)  # 금요일 10시 — 근무 중
OFF = datetime(2026, 11, 27, 19, 0, tzinfo=KST)  # 금요일 19시 — 근무 밖
MONDAY = datetime(2026, 11, 30, 8, 0, tzinfo=KST)  # 그 뒤 첫 근무 시작
PHONE = SENTINEL_DIGITS
OTHER_PHONE = "01000000188"
LANDLINE = "0220000199"
MARK = "QX71"  # 보낼 글·통화 목적에만 있는 표식 — 판정 글·사건·로그에 나오면 안 된다
BODY = f"내일 3층 타설 가능하신가요 {MARK}"
BUSY = "이미 보내는 중이거나 잠시 뒤 다시 해 보세요"
USER = Actor("user", 1, "김공정", "user")
AGENT = Actor("agent", 1, "에이전트", "user")
SYSTEM = Actor("system", None, "일꾼", None)
FIELD = Actor("user", 2, "박현장", "field")
DECISIONS = frozenset(GATE_RULES.values())
# 차례 하나에만 걸리는 경우 → (판정 코드, 차례). 근무시간은 문자·카카오톡이 scheduled, 전화가 blocked_hours.
CASES = {
    "test_mode": ("blocked_test", 1), "blocked_number": ("blocked_number", 2), "dnc": ("do_not_contact", 2),
    "off_hours": ("scheduled", 3), "daily": ("limit_daily", 4), "person": ("limit_person", 4),
    "agent_no_delegation": ("needs_approval", 5), "duplicate": ("duplicate", 6),
}


# ── 도우미(세 시험 파일이 같이 쓴다) ──────────────────────────────────


def connect(session, **over) -> NotifyConnection:
    """기본 알림 연결: 상태 ok, 시험 모드 끔, 모두 「승인 받기」."""
    values = {"name": "시험 연결", "base_url": "https://kat.invalid", "secret_ciphertext": "x", "secret_last4": "9999",
              "account_id": "acct-test", "sender_number": "07000000000", "is_default": True, "status": "ok",
              "test_mode": False, **over}
    conn = NotifyConnection(**values)
    session.add(conn)
    session.flush()
    return conn


def person(session, sid: int, phone: str | None = PHONE, **over) -> Contact:
    company = ContactCompany(schedule_id=sid, name="가람철근", trade="철근")
    session.add(company)
    session.flush()
    who = Contact(**{"schedule_id": sid, "company_id": company.id, "name": "박현장", "phone": phone, **over})
    session.add(who)
    session.flush()
    return who


def message(session, to: Contact | None = None, **over) -> OutreachMessage:
    values = {"direction": "out", "channel": "sms", "origin": "user", "origin_name": "김공정", "body": BODY, **over}
    if to is not None:
        values = {"schedule_id": to.schedule_id, "contact_id": to.id, **values}
    row = OutreachMessage(**values)
    session.add(row)
    session.flush()
    return row


def call(session, to: Contact | None = None, **over) -> OutreachCall:
    values = {"direction": "out", "origin": "user", "origin_name": "김공정", "purpose": f"타설 일정 확인 {MARK}", **over}
    if to is not None:
        values = {"schedule_id": to.schedule_id, "contact_id": to.id, **values}
    row = OutreachCall(**values)
    session.add(row)
    session.flush()
    return row


def row_for(session, channel: str, to: Contact | None = None, **over) -> OutreachMessage | OutreachCall:
    """그 채널(sms | kakao | call)의 나갈 줄 하나."""
    return call(session, to, **over) if channel == "call" else message(session, to, channel=channel, **over)


def kind_of(row) -> str:
    return "call" if isinstance(row, OutreachCall) else "message"


def send(row, actor: Actor = USER, now: datetime = WORK):
    """그 줄을 문에 넣는다(부르기 전에 session.commit() 을 해 둘 것 — 문은 자기 세션으로 읽는다)."""
    return gate.dispatch(kind_of(row), row.id, actor, now=now)


def reread(session, row):
    session.expire_all()
    return session.get(type(row), row.id)


def trail(session, row) -> list[tuple[str, str]]:
    """그 줄의 사건 (이름, 판정) — 남긴 차례대로."""
    session.expire_all()
    return [(e["rule"], e["verdict"]) for e in events.of(session, Ref(kind_of(row), row.id))]


def earlier(session, channel: str, to: Contact, when: datetime = WORK - timedelta(hours=1), **over):
    """앞서 나간(차지된) 줄 하나 — 상한 셈에 든다."""
    if channel == "call":
        return call(session, to, status="completed", claimed_at=when, **over)
    return message(session, to, **{"channel": channel, "status": "accepted", "claimed_at": when, "body": "앞서 보낸 글", **over})


def arrange(session, sid: int, case: str, channel: str = "sms"):
    """그 차례 하나에만 걸리는 줄을 만든다 → (줄, 부르는 쪽, 시각). case 는 CASES 의 열쇠 또는 "pass"."""
    conn = connect(session)
    who = person(session, sid)
    row = row_for(session, channel, who, purpose_key="pour-3f") if channel == "call" else row_for(session, channel, who)
    actor, now = USER, WORK
    if case == "test_mode":
        conn.test_mode = True
    elif case == "blocked_number":
        session.add(BlockedNumber(number=PHONE, reason="요청", created_by="관리자"))
    elif case == "dnc":
        who.do_not_contact = True
    elif case == "off_hours":
        now = OFF
    elif case == "daily":
        conn.limits_json = {"daily_sms_total": 1, "daily_calls_total": 1}
        earlier(session, channel, person(session, sid, OTHER_PHONE, name="이철근"))
    elif case == "person":
        conn.limits_json = {"per_contact_sms_daily": 1, "per_contact_calls_daily": 1}
        earlier(session, channel, who)
    elif case == "agent_no_delegation":
        actor = AGENT
    elif case == "duplicate":  # 30초 전에 같은 글(같은 목적의 통화)이 이미 나감
        just = WORK - timedelta(seconds=30)
        if channel == "call":
            call(session, who, status="completed", claimed_at=just, purpose_key="pour-3f")
        else:
            message(session, who, status="accepted", claimed_at=just)
    session.commit()
    return row, actor, now


def expected(case: str, channel: str) -> tuple[str, int]:
    code, rule = CASES[case]
    return ("blocked_hours" if code == "scheduled" and channel == "call" else code), rule


def db_path() -> Path:
    return Settings().data_dir / "chronos.db"


def leaks(text: str) -> bool:
    """그 글에 SENTINEL_PHONE(어느 꼴이든)·SENTINEL_KEY·보낼 글의 표식이 있는가."""
    digits = "".join(ch for ch in text if ch.isdigit())
    return SENTINEL_DIGITS in digits or SENTINEL_DIGITS[1:] in digits or SENTINEL_KEY in text or MARK in text


EVERY = [(case, channel) for case in [*sorted(CASES), "pass"] for channel in ("sms", "kakao", "call")]


# ── 차례 ────────────────────────────────────────────────────────────


async def test_order_is_test_mode_first(session, sid, fake_channel):
    """허용 안 된 번호 + 수신 거부 + 근무 밖 + 승인 받기인 에이전트 → 맨 앞 차례(시험 모드)만 보고한다."""
    connect(session, test_mode=True)
    row = message(session, person(session, sid, do_not_contact=True), origin="agent")
    session.commit()

    out = await send(row, AGENT, OFF)

    assert (out.code, out.rule) == ("blocked_test", 1)
    assert fake_channel.delivered == []
    assert trail(session, row) == [("test_mode", "blocked")]


@pytest.mark.parametrize("first", [2, 3, 4, 5, 6])
async def test_first_tripped_rule_is_reported(session, sid, fake_channel, first):
    """차례 first 부터 6까지 모두 걸리는 입력 → first 의 코드. 앞 차례가 뒤 차례를 가린다."""
    connect(session, limits_json={"daily_sms_total": 1} if first <= 4 else None)
    who = person(session, sid, do_not_contact=first <= 2)
    row = message(session, who, origin="agent")
    for when in (WORK, OFF):  # 30초 전에 같은 글이 나갔다 — 하루 상한(4)과 같은 글 두 번(6)에 걸린다
        message(session, who, status="accepted", claimed_at=when - timedelta(seconds=30))
    session.commit()

    out = await send(row, USER if first == 6 else AGENT, OFF if first <= 3 else WORK)

    codes = {2: "do_not_contact", 3: "scheduled", 4: "limit_daily", 5: "needs_approval", 6: "duplicate"}
    assert (out.code, out.rule) == (codes[first], first)
    assert fake_channel.delivered == []
    assert trail(session, row) == [(GATE_RULES[first], "blocked")]


async def test_precheck_comes_before_every_rule(session, sid, fake_channel):
    connect(session, test_mode=True)
    row = message(session, person(session, sid, do_not_contact=True))
    session.commit()

    out = await send(row, FIELD, OFF)

    assert (out.code, out.rule) == ("not_sendable", 0)
    assert trail(session, row) == [("precheck", "blocked")]


@pytest.mark.parametrize("case,code,rule", [
    ("blocked_number", "blocked_number", 2), ("dnc", "do_not_contact", 2), ("off_hours_sms", "scheduled", 3),
    ("off_hours_call", "blocked_hours", 3), ("daily", "limit_daily", 4), ("person", "limit_person", 4),
    ("agent_no_delegation", "needs_approval", 5), ("live_call", "duplicate", 6),
])
async def test_each_rule_blocks_without_delivering(session, sid, fake_channel, case, code, rule):
    if case == "live_call":
        connect(session)
        who = person(session, sid)
        call(session, who, status="dialing", claimed_at=WORK - timedelta(minutes=5))
        row, actor, now = call(session, who), USER, WORK
        session.commit()
    else:
        channel = "call" if case == "off_hours_call" else "sms"
        row, actor, now = arrange(session, sid, case.removesuffix("_sms").removesuffix("_call"), channel)

    out = await send(row, actor, now)

    assert out.code == code and out.rule == rule and fake_channel.delivered == []
    assert trail(session, row) == [(GATE_RULES[rule], "blocked")]
    assert reread(session, row).claimed_at is None  # 나가지 않은 줄은 그날 셈에 들지 않는다


@pytest.mark.parametrize("channel", ["sms", "kakao", "call"])
@pytest.mark.parametrize("case", sorted(CASES))
async def test_same_checks_for_every_channel(session, sid, fake_channel, channel, case):
    """세 채널 모두 같은 차례·같은 코드(근무시간만 문자·카카오톡은 예약, 전화는 막음), 걸리면 통로를 부르지 않는다."""
    row, actor, now = arrange(session, sid, case, channel)

    out = await send(row, actor, now)

    code, rule = expected(case, channel)
    assert (out.code, out.rule) == (code, rule)
    assert fake_channel.delivered == []
    state = {"blocked_test": "blocked_test", "scheduled": "scheduled", "blocked_hours": "blocked_hours"}.get(code, "draft")
    row = reread(session, row)
    assert row.status == state
    if state == "draft":
        assert row.fail_reason and row.send_mode is None  # 초안으로 돌아간 줄에는 까닭이 남고 보낸 방식은 비어 있다


@pytest.mark.parametrize("channel,code,state", [("sms", "accepted", "accepted"), ("kakao", "accepted", "accepted"),
                                                ("call", "queued", "queued")])
async def test_every_channel_passes_when_nothing_trips(session, sid, fake_channel, channel, code, state):
    row, actor, now = arrange(session, sid, "pass", channel)

    out = await send(row, actor, now)

    assert (out.code, out.rule, out.scheduled_at) == (code, None, None)
    lane = "sms" if channel == "kakao" else channel  # 카카오톡은 잠겨 있어 문자로 나간다
    assert [(d.channel, d.row_id) for d in fake_channel.delivered] == [(lane, row.id)]
    row = reread(session, row)
    assert row.status == state and row.send_mode == "manual" and row.fail_reason is None
    assert as_utc(row.claimed_at) == WORK


# ── 지나간 줄 ────────────────────────────────────────────────────────


async def test_accepted_message_keeps_what_the_channel_said(session, sid, fake_channel):
    row, actor, now = arrange(session, sid, "pass")
    fake_channel.result = Delivered("sent", provider_id="kat-msg-1")

    out = await send(row, actor, now)

    row = reread(session, row)
    assert out.code == "accepted"
    assert (row.status, row.provider_message_id, as_utc(row.sent_at)) == ("accepted", "kat-msg-1", WORK)
    assert trail(session, row) == [("channel_choice", "allowed"), ("delivery", "allowed")]
    assert events.of(session, Ref("message", row.id))[0]["detail"] == "sms"


async def test_blocked_test_writes_row_and_delivers_nothing(session, sid, fake_channel):
    connect(session, test_mode=True, allow_numbers_json=["010-0000-0188"])
    row = message(session, person(session, sid))
    session.commit()

    out = await send(row)

    row = reread(session, row)
    assert out.code == "blocked_test" and fake_channel.delivered == []
    assert (row.status, row.claimed_at, row.sent_at) == ("blocked_test", None, None)
    assert (await send(row)).code == "not_sendable"  # 기록만 남은 줄 — 다시 보내지 않는다
    assert fake_channel.delivered == []


async def test_allowed_number_passes_in_test_mode(session, sid, fake_channel):
    connect(session, test_mode=True, allow_numbers_json=[SENTINEL_PHONE])  # 줄표가 있는 꼴로 적혀 있어도 같은 번호
    row = message(session, person(session, sid))
    session.commit()

    assert (await send(row)).code == "accepted"
    assert len(fake_channel.delivered) == 1


async def test_human_send_of_agent_draft_is_approved_by_name(session, sid, fake_channel):
    connect(session)
    row = message(session, person(session, sid), origin="agent", origin_name="에이전트")
    session.commit()

    assert (await send(row, USER)).code == "accepted"

    row = reread(session, row)
    assert row.send_mode == "approved" and row.approved_by == "김공정"


async def test_row_without_contact_uses_peer_number(session, sid, fake_channel):
    """주소록에 없는 번호에게 가는 줄(연락처 없음) — 번호는 peer_number, 같은 검사를 받는다."""
    conn = connect(session, test_mode=True, allow_numbers_json=[OTHER_PHONE])
    row = message(session, peer_number=PHONE)
    session.commit()
    assert (await send(row)).code == "blocked_test"

    conn.allow_numbers_json = [PHONE]
    again = message(session, peer_number=PHONE)
    session.commit()
    assert (await send(again)).code == "accepted"
    assert [d.row_id for d in fake_channel.delivered] == [again.id]


async def test_field_role_cannot_dispatch(session, sid, fake_channel):
    connect(session)
    row = message(session, person(session, sid), status="scheduled", send_mode="manual", scheduled_at=WORK)
    session.commit()

    out = await send(row, FIELD)

    assert (out.code, out.rule) == ("not_sendable", 0) and fake_channel.delivered == []
    row = reread(session, row)
    assert (row.status, row.send_mode) == ("scheduled", "manual")  # 보낼 수 없는 사람이 눌러도 예약은 그대로다
    assert (await send(row, Actor("agent", 2, "에이전트", "field"))).code == "not_sendable"
    assert (await send(row, Actor("user", 3, "이름없음", None))).code == "not_sendable"
    assert (await send(row, Actor("robot", None, "모름", None))).code == "not_sendable"
    assert fake_channel.delivered == []


async def test_missing_or_inbound_row_is_not_sendable(session, sid, fake_channel):
    connect(session)
    inbound = message(session, person(session, sid), direction="in", origin="peer", status="draft")
    session.commit()

    assert (await gate.dispatch("message", 987654, USER, now=WORK)).code == "not_sendable"
    assert (await gate.dispatch("call", 987654, USER, now=WORK)).code == "not_sendable"
    assert (await send(inbound)).code == "not_sendable"
    assert fake_channel.delivered == [] and trail(session, inbound) == []


# ── 통로 결과 ────────────────────────────────────────────────────────


async def test_delivery_failure_marks_failed_with_clean_reason(session, sid, fake_channel, caplog):
    caplog.set_level(logging.DEBUG)
    redact.add_secrets(SENTINEL_KEY)
    row, actor, now = arrange(session, sid, "pass")
    fake_channel.result = Delivered("failed", fail_code="sender_not_registered",
                                    fail_text=f"발신번호가 등록되지 않았습니다 {SENTINEL_PHONE} {SENTINEL_KEY}")

    out = await send(row, actor, now)

    row = reread(session, row)
    assert (out.code, out.rule) == ("failed", None)  # 문은 지나갔고 통로가 보내지 못함 — 「보내기를 거절함」(not_sendable)이 아니다
    assert row.status == "failed" and row.fail_reason.startswith("발신번호가 등록되지 않았습니다")
    assert out.message == row.fail_reason  # 통로가 준 한국어 까닭 그대로(비밀·번호는 지운 것)
    assert trail(session, row) == [("channel_choice", "allowed"), ("delivery", "blocked")]
    stored = json.dumps(events.of(session, Ref("message", row.id)), ensure_ascii=False)
    assert not any(leaks(text) for text in (out.message, row.fail_reason, stored))
    assert_clean(caplog)


async def test_failed_row_cannot_be_dispatched_again(session, sid, fake_channel):
    row, actor, now = arrange(session, sid, "pass")
    fake_channel.result = Delivered("failed", fail_text="보내지 못했습니다")
    await send(row, actor, now)
    fake_channel.result = None

    out = await send(row, actor, now + timedelta(minutes=10))

    assert (out.code, out.rule) == ("not_sendable", 0)  # 다시 보내기는 새 줄
    assert len(fake_channel.delivered) == 1 and reread(session, row).status == "failed"


async def test_retry_row_after_a_failure_goes_out_at_once(session, sid, fake_channel):
    """실패한 줄과 같은 글의 새 줄(다시 보내기)은 바로 나간다 — 가지 않은 글은 「같은 글 두 번」이 아니다."""
    row, actor, now = arrange(session, sid, "pass")
    fake_channel.result = Delivered("failed", fail_text="보내지 못했습니다")
    await send(row, actor, now)
    fake_channel.result = None
    retry = message(session, session.get(Contact, row.contact_id))
    session.commit()

    assert (await send(retry, actor, now + timedelta(seconds=20))).code == "accepted"


async def test_unsure_delivery_is_unconfirmed_and_never_resent(session, sid, fake_channel):
    row, actor, now = arrange(session, sid, "pass")
    fake_channel.result = Delivered("unsure", fail_code="timeout", fail_text="결과를 알 수 없습니다")

    out = await send(row, actor, now)

    assert (out.code, out.message) == ("unsure", "보냈는지 확인 필요")
    assert reread(session, row).status == "unconfirmed"
    assert trail(session, row) == [("channel_choice", "allowed"), ("delivery", "noted")]
    fake_channel.result = None
    for actor in (USER, SYSTEM):
        assert (await send(row, actor, now + timedelta(hours=1))).code == "not_sendable"
    assert len(fake_channel.delivered) == 1 and reread(session, row).status == "unconfirmed"


async def test_channel_exception_is_unsure_and_logs_only_the_kind(session, sid, fake_channel, caplog):
    """통로가 예외로 끝나면 나갔는지 모른다 — 실패로 적지 않는다. 로그에는 예외 종류만."""
    caplog.set_level(logging.DEBUG)
    row, actor, now = arrange(session, sid, "pass")
    fake_channel.result = RuntimeError(f"POST /messages to={SENTINEL_PHONE} key={SENTINEL_KEY} 실패")

    out = await send(row, actor, now)

    assert out.code == "unsure" and reread(session, row).status == "unconfirmed"
    assert "RuntimeError" in caplog.text
    assert_clean(caplog)


async def test_cancelled_delivery_is_unsure(session, sid, fake_channel):
    row, actor, now = arrange(session, sid, "pass")
    started = asyncio.Event()

    async def hang(_row_id):
        started.set()
        await asyncio.Event().wait()

    fake_channel.during = hang
    task = asyncio.create_task(send(row, actor, now))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert reread(session, row).status == "unconfirmed"
    assert trail(session, row) == [("channel_choice", "allowed"), ("delivery", "noted")]
    fake_channel.during = None
    assert (await send(row, actor, now)).code == "not_sendable"
    assert len(fake_channel.delivered) == 1


async def test_channel_that_raises_cancelled_gives_unsure_outcome(session, sid, fake_channel):
    """통로 안쪽 호출이 취소된 것(문을 부른 쪽은 취소되지 않음) → 판정 unsure 를 돌려준다."""
    row, actor, now = arrange(session, sid, "pass")

    def cancelled_inside(_row_id):
        raise asyncio.CancelledError

    fake_channel.during = cancelled_inside

    out = await send(row, actor, now)

    assert out.code == "unsure" and reread(session, row).status == "unconfirmed"


@pytest.mark.parametrize("result", [Delivered("failed", fail_text="통화 일꾼이 꺼져 있습니다"), RuntimeError("boom")])
async def test_call_that_could_not_be_queued_is_failed(session, sid, fake_channel, result):
    """통화 통로가 줄에 넣지 못했다 → queued 로 남기지 않는다(걸리지도 않을 통화가 「진행 중」으로 남아 다음 걸기를 막지 않게)."""
    row, actor, now = arrange(session, sid, "pass", "call")
    fake_channel.result = result

    out = await send(row, actor, now)

    assert (out.code, out.rule) == ("failed", None)
    row = reread(session, row)
    assert row.status == "failed" and row.fail_reason
    assert trail(session, row)[0] == ("channel_choice", "allowed") and trail(session, row)[1][0] == "delivery"


# ── 동시성·잠금 ──────────────────────────────────────────────────────


async def test_concurrent_dispatch_delivers_once(session, sid, fake_channel):
    """같은 줄을 두 곳에서: 첫째가 보내는 동안 온 둘째는 duplicate — 「이미 보냈습니다」라고 하지 않는다."""
    row, actor, now = arrange(session, sid, "pass")
    in_flight, release = asyncio.Event(), asyncio.Event()

    async def hold(_row_id):
        in_flight.set()
        await release.wait()

    fake_channel.during = hold
    first = asyncio.create_task(send(row, actor, now))
    await asyncio.wait_for(in_flight.wait(), 5)
    second = await send(row, actor, now)
    release.set()

    assert (second.code, second.rule, second.message) == ("duplicate", 6, BUSY)
    assert (await first).code == "accepted"
    assert len(fake_channel.delivered) == 1 and reread(session, row).status == "accepted"


@pytest.mark.parametrize("channel", ["sms", "call"])
async def test_racing_dispatches_of_one_row_deliver_once(session, sid, fake_channel, channel):
    row, actor, now = arrange(session, sid, "pass", channel)

    outs = await asyncio.gather(*(send(row, actor, now) for _ in range(6)))

    codes = sorted(o.code for o in outs)
    assert len(fake_channel.delivered) == 1
    assert codes.count("accepted" if channel == "sms" else "queued") == 1
    assert set(codes) <= {"accepted", "queued", "duplicate", "not_sendable"}  # 진 쪽: 보내는 중이면 duplicate, 끝났으면 not_sendable


async def test_racing_rows_with_the_same_text_send_one(session, sid, fake_channel):
    """두 번 눌러 생긴 두 줄(같은 사람·같은 글)을 동시에 → 하나만 나간다."""
    connect(session)
    who = person(session, sid)
    rows = [message(session, who) for _ in range(4)]
    session.commit()

    outs = await asyncio.gather(*(send(row) for row in rows))

    assert sorted(o.code for o in outs) == ["accepted", "duplicate", "duplicate", "duplicate"]
    assert len(fake_channel.delivered) == 1


async def test_racing_rows_cannot_pass_a_limit_together(session, sid, fake_channel):
    """상한까지 한 자리 남았을 때 서로 다른 글 넷을 동시에 → 하나만 나간다(셈과 차지가 한 묶음)."""
    connect(session, limits_json={"per_contact_sms_daily": 1})
    who = person(session, sid)
    rows = [message(session, who, body=f"물음 {i}") for i in range(4)]
    session.commit()

    outs = await asyncio.gather(*(send(row) for row in rows))

    assert sorted(o.code for o in outs) == ["accepted", "limit_person", "limit_person", "limit_person"]
    assert len(fake_channel.delivered) == 1


async def test_no_write_lock_during_delivery(session, sid, fake_channel):
    """통로를 부르는 동안 문은 세션도 쓰기 잠금도 쥐고 있지 않다 — 다른 연결이 곧바로 쓸 수 있다."""
    row, actor, now = arrange(session, sid, "pass")
    seen = {}

    def during(row_id):
        seen["checked_out"] = db._engine.pool.checkedout()
        with closing(sqlite3.connect(db_path(), timeout=0)) as other:
            other.execute("BEGIN EXCLUSIVE")
            seen["status"] = other.execute("SELECT status FROM outreach_messages WHERE id = ?", (row_id,)).fetchone()[0]
            other.rollback()

    fake_channel.during = during
    row_id = row.id
    session.rollback()  # 시험 세션도 연결을 돌려놓는다 — 남은 것은 문이 쥔 것뿐

    assert (await gate.dispatch("message", row_id, actor, now=now)).code == "accepted"
    assert seen == {"checked_out": 0, "status": "sending"}  # 차지는 이미 commit 됐다


async def test_locked_database_claim_is_not_a_send(session, sid, fake_channel, monkeypatch):
    """claim 이 False(누가 먼저 차지했거나 DB 가 잠김) → 통로 0번, 줄은 그대로, 글은 「잠시 뒤 다시」."""
    row, actor, now = arrange(session, sid, "pass")
    monkeypatch.setattr(outreach, "claim", lambda *args, **kwargs: False)

    out = await send(row, actor, now)

    assert (out.code, out.rule, out.message) == ("duplicate", 6, BUSY)
    assert fake_channel.delivered == []
    row = reread(session, row)
    assert (row.status, row.fail_reason, row.send_mode, row.claimed_at) == ("draft", None, None, None)
    assert trail(session, row) == [("duplicate", "blocked")]


async def test_database_held_by_another_writer_is_not_a_send(session, sid, fake_channel, monkeypatch):
    """다른 쓰기가 DB 를 쥐고 놓지 않는다 → 보내지 않고 「잠시 뒤 다시」(예외가 새지 않는다)."""
    row, actor, now = arrange(session, sid, "pass")
    impatient = create_engine(f"sqlite:///{db_path()}", connect_args={"timeout": 0.1}, hide_parameters=True)
    monkeypatch.setattr(db, "_engine", impatient)
    try:
        with closing(sqlite3.connect(db_path())) as holder:
            holder.execute("BEGIN IMMEDIATE")
            out = await send(row, actor, now)
            holder.rollback()
    finally:
        impatient.dispose()

    assert (out.code, out.rule, out.message) == ("duplicate", 6, BUSY) and fake_channel.delivered == []
    row = reread(session, row)
    assert (row.status, row.claimed_at, row.send_mode) == ("draft", None, None)


async def test_gate_reads_committed_rows_not_the_callers_session(session, sid, fake_channel):
    """문은 부른 쪽 세션을 받지 않는다 — 부른 쪽이 commit 한 것만 보고, commit 하지 않은 것에는 기대지 않는다."""
    assert list(inspect.signature(gate.dispatch).parameters) == ["kind", "row_id", "actor", "now"]
    row, actor, now = arrange(session, sid, "pass")
    row_id = row.id
    with session.no_autoflush:
        row.status = "accepted"  # 부른 쪽 세션에만 있는(flush·commit 하지 않은) 바뀜
        out = await gate.dispatch("message", row_id, actor, now=now)
        session.rollback()

    assert out.code == "accepted" and len(fake_channel.delivered) == 1


# ── 사건 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("case,channel", EVERY)
async def test_every_decision_leaves_one_event(session, sid, fake_channel, case, channel):
    """dispatch 한 번마다 문 판정 사건이 꼭 하나(걸리면 그 차례, 지나가면 channel_choice). 노트는 판정 앞, delivery 는 따로 뒤."""
    row, actor, now = arrange(session, sid, case, channel)

    out = await send(row, actor, now)

    got = trail(session, row)
    decisions = [(rule, verdict) for rule, verdict in got if rule in DECISIONS]
    if case == "pass":
        assert decisions == [("channel_choice", "allowed")]
        assert got[-2:] == [("channel_choice", "allowed"), ("delivery", "allowed")]
        assert got[:-2] == ([("kakao_not_ready", "noted")] if channel == "kakao" else [])
    else:
        assert decisions == got == [(GATE_RULES[out.rule], "blocked")]


async def test_rescheduled_row_has_one_decision_per_attempt_in_order(session, sid, fake_channel):
    """근무 밖 dispatch → working_hours, 때가 돼 일꾼이 다시 dispatch → 처음부터 다시 보고 channel_choice·delivery."""
    row, actor, _ = arrange(session, sid, "pass")

    first = await send(row, actor, OFF)
    assert first.code == "scheduled" and fake_channel.delivered == []
    second = await send(row, SYSTEM, MONDAY)

    assert second.code == "accepted"
    assert trail(session, row) == [("working_hours", "blocked"), ("channel_choice", "allowed"), ("delivery", "allowed")]
    row = reread(session, row)
    assert (row.status, row.send_mode) == ("accepted", "manual")  # 예약할 때 누른 사람의 방식이 그대로 남는다


@pytest.mark.parametrize("case,channel", EVERY)
async def test_codes_rules_and_event_names_are_the_shared_constants(session, sid, fake_channel, case, channel):
    """나온 code·rule·사건 이름이 모두 harness.types 의 집합 안이고, 판정 글·사건·까닭에 번호도 보낼 글도 없다."""
    row, actor, now = arrange(session, sid, case, channel)

    out = await send(row, actor, now)

    log = events.of(session, Ref(kind_of(row), row.id))
    assert out.code in get_args(OutcomeCode) and (out.rule is None or out.rule in GATE_RULES)
    assert {e["rule"] for e in log} <= DECISIONS | GATE_NOTES | {"delivery"} <= events.KNOWN_RULES
    row = reread(session, row)
    assert not any(leaks(text) for text in (out.message, row.fail_reason or "", json.dumps(log, ensure_ascii=False)))


# ── 구조 ────────────────────────────────────────────────────────────


def _deliver_callers() -> set[str]:
    root = Path(app.__file__).parent
    found = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "deliver":
                found.add(path.relative_to(root).as_posix())
    return found


def test_only_gate_calls_deliver():
    """Channel.deliver 를 부르는 코드는 나가는 문 하나뿐이다(backend/app 전체를 훑는다)."""
    assert _deliver_callers() == {"outreach/harness/gate.py"}
