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
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import get_args

import pytest
from sqlalchemy import create_engine, delete, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import app
from app import db
from app.config import Settings
from app.outreach import hours
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
RAW = "RAWTXT7"  # 통로가 돌려준 글에만 있는 표식 — 판정 글·줄·사건 어디에도 남으면 안 된다
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

    # 3·4 는 사람이 넣는다 — 위임 없는 에이전트는 권한(5)을 근무시간(3)·상한(4)보다 먼저 본다(Task 81 고침 1)
    out = await send(row, USER if first in (3, 4, 6) else AGENT, OFF if first <= 3 else WORK)

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
    """통로가 준 글은 판정 글·줄·사건에 흘리지 않는다 — fail_code 를 문이 정해 둔 한국어 문장으로 옮긴다."""
    caplog.set_level(logging.DEBUG)
    row, actor, now = arrange(session, sid, "pass")
    fake_channel.result = Delivered("failed", fail_code="bad_sender",
                                    fail_text=f"{RAW} to={SENTINEL_PHONE} 010-0000 key={SENTINEL_KEY} kat-test-key")

    out = await send(row, actor, now)

    row = reread(session, row)
    assert (out.code, out.rule) == ("failed", None)  # 문은 지나갔고 통로가 보내지 못함 — 「보내기를 거절함」(not_sendable)이 아니다
    assert row.status == "failed" and out.message == row.fail_reason == gate.FAIL_TEXT["bad_sender"]
    assert trail(session, row) == [("channel_choice", "allowed"), ("delivery", "blocked")]
    stored = json.dumps(events.of(session, Ref("message", row.id)), ensure_ascii=False)
    for kept in (out.message, row.fail_reason, stored):
        assert not leaks(kept) and RAW not in kept and "kat-test" not in kept and "0000" not in kept
    assert_clean(caplog)


@pytest.mark.parametrize("code", [None, "", "no_such_code", f"bad_sender {RAW}"])
async def test_unknown_failure_code_gets_the_generic_sentence(session, sid, fake_channel, code):
    row, actor, now = arrange(session, sid, "pass")
    fake_channel.result = Delivered("failed", fail_code=code, fail_text=RAW)

    out = await send(row, actor, now)

    row = reread(session, row)
    assert out.code == "failed" and out.message == row.fail_reason == gate.SEND_FAILED
    assert RAW not in json.dumps(events.of(session, Ref("message", row.id)), ensure_ascii=False)


def _sms_channel_codes() -> set[str]:
    """문자 통로가 스스로 돌려주는 fail_code 전부 — 모듈을 불러오지 않고(불러오면 통로가 등록된다) 글을 읽는다:
    `fail_code=` 에 준 글자·모듈 상수, 그리고 제공사 code 를 바꿔 주는 _CODES 의 값."""
    tree = ast.parse((Path(app.__file__).parent / "outreach/channels/sms.py").read_text(encoding="utf-8"))
    constants, codes = {}, set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            constants[node.targets[0].id] = ast.literal_eval(node.value) if isinstance(node.value, ast.Constant | ast.Dict) else None
    codes.update(constants["_CODES"].values())
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "fail_code":
            if isinstance(node.value, ast.Constant):
                codes.add(node.value.value)
            elif isinstance(node.value, ast.Name):
                codes.add(constants[node.value.id])
    return codes


def test_every_code_the_sms_channel_returns_has_a_sentence():
    """통로가 스스로 쓰는 코드도 「보내지 못했습니다」 대신 무슨 일이 있었는지 말한다 — 번호·제공사의 글·숫자 없이."""
    codes = _sms_channel_codes()
    assert {"not_sendable", "not_reachable", "local_error", "bad_sender", "network"} <= codes
    assert codes <= set(gate.FAIL_TEXT)
    for code in ("not_sendable", "not_reachable", "local_error"):
        sentence = gate.FAIL_TEXT[code]
        assert sentence != gate.SEND_FAILED and "보내지 않았습니다" in sentence
        assert not any(ch.isdigit() or ch.isascii() and ch.isalpha() for ch in sentence)  # 숫자·영문(코드·제공사 글) 없음


@pytest.mark.parametrize("code", ["not_sendable", "not_reachable", "local_error"])
async def test_channel_own_failure_codes_reach_the_row_as_sentences(session, sid, fake_channel, code):
    row, actor, now = arrange(session, sid, "pass")
    fake_channel.result = Delivered("failed", fail_code=code, fail_text=RAW)

    out = await send(row, actor, now)

    row = reread(session, row)
    assert (out.code, row.status) == ("failed", "failed") and out.message == row.fail_reason == gate.FAIL_TEXT[code]


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
    fake_channel.result = Delivered("unsure", fail_code="timeout", fail_text=f"결과를 알 수 없습니다 {RAW}")

    out = await send(row, actor, now)

    assert (out.code, out.message) == ("unsure", "보냈는지 확인 필요")
    assert (reread(session, row).status, reread(session, row).fail_reason) == ("unconfirmed", gate.UNSURE)
    assert RAW not in json.dumps(events.of(session, Ref("message", row.id)), ensure_ascii=False)
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


async def test_call_that_could_not_be_queued_is_failed(session, sid, fake_channel):
    """통화 통로가 줄에 넣지 못했다고 분명히 알렸다 → failed(queued 로 남아 다음 걸기를 막지 않는다). 곧바로 다시 걸 수 있다."""
    row, actor, now = arrange(session, sid, "pass", "call")
    fake_channel.result = Delivered("failed", fail_code="network", fail_text=RAW)

    out = await send(row, actor, now)

    assert (out.code, out.rule, out.message) == ("failed", None, gate.FAIL_TEXT["network"])
    row = reread(session, row)
    assert (row.status, row.fail_reason) == ("failed", gate.FAIL_TEXT["network"])
    assert trail(session, row) == [("channel_choice", "allowed"), ("delivery", "blocked")]
    fake_channel.result = None
    redial = call(session, session.get(Contact, row.contact_id), purpose_key="pour-3f")
    session.commit()
    assert (await send(redial, actor, now + timedelta(seconds=10))).code == "queued"


def _raise_cancelled(_row_id):
    raise asyncio.CancelledError


@pytest.mark.parametrize("ending", ["exception", "unsure", "cancelled_inside"])
async def test_call_closed_without_a_clear_answer_is_unsure_and_blocks_a_redial(session, sid, fake_channel, ending):
    """통화 통로가 예외·모름·취소로 끝났다(걸렸을 수도 있다) → 부른 쪽에는 「확인 필요」, 줄은 failed 로 닫되 그 번호로의 다음
    전화는 DUPLICATE_WINDOW_S 동안 막는다(같은 사람에게 두 번 거는 일이 없게)."""
    row, actor, now = arrange(session, sid, "pass", "call")
    if ending == "exception":
        fake_channel.result = RuntimeError(f"boom {SENTINEL_PHONE}")
    elif ending == "unsure":
        fake_channel.result = Delivered("unsure", fail_text=RAW)
    else:
        fake_channel.during = _raise_cancelled

    out = await send(row, actor, now)

    assert (out.code, out.rule, out.message) == ("unsure", None, gate.UNSURE)
    row = reread(session, row)
    assert (row.status, row.fail_reason) == ("failed", gate.UNSURE)
    assert trail(session, row) == [("channel_choice", "allowed"), ("delivery", "noted")]
    fake_channel.result = fake_channel.during = None
    who = session.get(Contact, row.contact_id)
    soon, later = call(session, who, purpose_key="another-purpose"), call(session, who, purpose_key="another-purpose")
    session.commit()
    blocked = await send(soon, actor, now + timedelta(seconds=10))
    assert (blocked.code, blocked.rule) == ("duplicate", 6) and len(fake_channel.delivered) == 1
    assert (await send(later, actor, now + timedelta(seconds=gate.DUPLICATE_WINDOW_S + 1))).code == "queued"


@pytest.mark.parametrize("result", [RuntimeError("boom"), Delivered("failed", fail_code="network"), Delivered("unsure")])
async def test_call_the_worker_already_took_is_not_closed_as_failed(session, sid, fake_channel, result):
    """통로가 줄에 넣은 뒤 일꾼이 벌써 걸기 시작했는데(queued → dialing) 통로 호출이 실패로 끝났다 → 그 줄을 failed 로 덮지
    않는다(덮으면 「진행 중 통화」 검사가 풀려 같은 사람에게 한 통이 더 나간다)."""
    row, actor, now = arrange(session, sid, "pass", "call")

    def worker_takes_it(row_id):
        with Session(db._engine) as other:
            assert outreach.claim(other, "call", row_id, ("queued",), "dialing")
            other.commit()

    fake_channel.during, fake_channel.result = worker_takes_it, result

    out = await send(row, actor, now)

    assert out.code == "unsure"
    row = reread(session, row)
    assert (row.status, row.fail_reason) == ("dialing", None)
    fake_channel.during = fake_channel.result = None
    redial = call(session, session.get(Contact, row.contact_id), purpose_key="pour-3f")
    session.commit()
    assert (await send(redial, actor, now + timedelta(seconds=10))).code == "duplicate"
    assert len(fake_channel.delivered) == 1


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


# ── 잠금 실패·결과 적기·스레드(고침 1) ────────────────────────────────


@pytest.fixture
def impatient(monkeypatch):
    """기다림이 짧은 엔진으로 바꿔 끼운다(잠긴 DB 를 0.1초만 기다린다 — 나머지는 앱의 엔진과 같다)."""
    engine = create_engine(f"sqlite:///{db_path()}", connect_args={"timeout": 0.1}, hide_parameters=True)
    monkeypatch.setattr(db, "_engine", engine)
    yield engine
    engine.dispose()


def assert_released(engine=None):
    """문이 쓴 연결이 트랜잭션을 쥔 채 풀에 돌아가 있지 않고, 다른 연결이 곧바로 쓸 수 있다."""
    with (engine or db._engine).connect() as pooled:
        assert pooled.connection.driver_connection.in_transaction is False
    with closing(sqlite3.connect(db_path(), timeout=0)) as other:
        other.execute("BEGIN IMMEDIATE")
        other.rollback()


async def test_commit_that_cannot_get_the_lock_is_busy_and_leaves_nothing_behind(session, sid, fake_channel, impatient):
    """다른 연결이 읽기 잠금을 쥐고 있으면 BEGIN IMMEDIATE 는 되는데 commit 이 실패한다 → 예외 없이 「잠시 뒤 다시」,
    되돌려서 차지한 것도 사건도 남지 않고, 그 연결은 트랜잭션을 놓은 채 풀로 돌아간다."""
    row, actor, now = arrange(session, sid, "pass")
    row_id = row.id
    session.rollback()
    with closing(sqlite3.connect(db_path(), isolation_level=None)) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM outreach_messages").fetchone()
        out = await gate.dispatch("message", row_id, actor, now=now)
        reader.execute("ROLLBACK")

    assert (out.code, out.rule, out.message) == ("duplicate", 6, BUSY) and fake_channel.delivered == []
    assert_released(impatient)
    row = reread(session, row)
    assert (row.status, row.claimed_at, row.send_mode) == ("draft", None, None) and trail(session, row) == []
    assert (await send(row, actor, now)).code == "accepted"  # 잠금이 풀리면 그대로 나간다(딱 한 번)
    assert len(fake_channel.delivered) == 1


async def test_result_that_cannot_be_written_is_unsure_not_an_error(session, sid, fake_channel, impatient, caplog):
    """통로는 보냈는데 결과를 적지 못한다(DB 가 잠김) → 예외가 아니라 「보냈는지 확인 필요」. 줄은 sending 으로 남고, 남아 있는
    동안은 시간이 얼마나 지나든 같은 글의 새 줄을 막는다."""
    caplog.set_level(logging.DEBUG)
    row, actor, now = arrange(session, sid, "pass")
    who_id = row.contact_id
    session.rollback()
    holder = sqlite3.connect(db_path(), isolation_level=None)
    fake_channel.during = lambda _row_id: holder.execute("BEGIN IMMEDIATE")
    try:
        out = await gate.dispatch("message", row.id, actor, now=now)
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    assert (out.code, out.rule, out.message) == ("unsure", None, gate.UNSURE)
    assert len(fake_channel.delivered) == 1 and reread(session, row).status == "sending"
    assert "OperationalError" in caplog.text
    assert_clean(caplog)
    assert_released(impatient)
    fake_channel.during = None
    twin = message(session, session.get(Contact, who_id))
    session.commit()
    again = await send(twin, actor, now + timedelta(hours=3))
    assert (again.code, again.rule) == ("duplicate", 6) and len(fake_channel.delivered) == 1


async def test_result_write_is_retried(session, sid, fake_channel, monkeypatch):
    """결과 적기가 한 번 실패해도 다시 해 본다 — 적히면 보통 때와 같다(제공사 id 를 잃지 않는다)."""
    row, actor, now = arrange(session, sid, "pass")
    fake_channel.result = Delivered("sent", provider_id="kat-msg-9")
    real, failed = events.record, []

    def flaky(session_, ref, rule, *args, **kwargs):
        if rule == "delivery" and not failed:
            failed.append(rule)
            raise OperationalError("UPDATE", {}, sqlite3.OperationalError("database is locked"))
        return real(session_, ref, rule, *args, **kwargs)

    monkeypatch.setattr(events, "record", flaky)

    out = await send(row, actor, now)

    row = reread(session, row)
    assert out.code == "accepted" and failed == ["delivery"]
    assert (row.status, row.provider_message_id) == ("accepted", "kat-msg-9")
    assert trail(session, row) == [("channel_choice", "allowed"), ("delivery", "allowed")]


@pytest.mark.parametrize("channel,code", [("sms", "accepted"), ("call", "queued")])
async def test_row_deleted_while_the_channel_was_busy_does_not_raise(session, sid, fake_channel, channel, code):
    """통로를 부르는 동안 줄이 지워졌다(일정 지우기) → 적을 곳이 없을 뿐, 예외를 올리지 않는다."""
    row, actor, now = arrange(session, sid, "pass", channel)
    model = type(row)

    def gone(row_id):
        with Session(db._engine) as other:
            other.execute(delete(model).where(model.id == row_id))
            other.commit()

    fake_channel.during = gone

    assert (await send(row, actor, now)).code == code


async def test_loop_stays_responsive_while_the_gate_waits_for_the_database(session, sid, fake_channel):
    """문이 DB 를 기다리는 동안 이벤트 루프는 돈다 — 잠금을 푸는 일이 같은 루프에서 돌아야 문이 지나간다."""
    row, actor, now = arrange(session, sid, "pass")
    row_id = row.id
    session.rollback()
    with closing(sqlite3.connect(db_path(), isolation_level=None)) as holder:
        holder.execute("BEGIN IMMEDIATE")

        async def release():
            await asyncio.sleep(0.3)  # 문이 루프를 막고 있으면 여기가 돌지 못해 문은 「잠시 뒤 다시」로 끝난다
            holder.execute("ROLLBACK")

        started = time.monotonic()
        out, _ = await asyncio.gather(gate.dispatch("message", row_id, actor, now=now), release())

    assert out.code == "accepted" and time.monotonic() - started >= 0.3


async def test_settle_does_not_block_the_loop(session, sid, fake_channel):
    """통로가 돌아온 뒤 결과를 적으려고 DB 를 기다리는 동안에도 이벤트 루프는 돈다."""
    row, actor, now = arrange(session, sid, "pass")
    row_id = row.id
    session.rollback()
    with closing(sqlite3.connect(db_path(), isolation_level=None)) as holder:
        releasing = []

        async def release():
            await asyncio.sleep(0.3)  # 결과 적기가 루프를 막고 있으면 여기가 돌지 못해 끝내 적지 못한다(unsure)
            holder.execute("ROLLBACK")

        def grab(_row_id):
            holder.execute("BEGIN IMMEDIATE")
            releasing.append(asyncio.ensure_future(release()))

        fake_channel.during = grab
        out = await gate.dispatch("message", row_id, actor, now=now)
        await asyncio.gather(*releasing)

    assert out.code == "accepted" and reread(session, row).status == "accepted"


async def test_gate_waits_about_a_second_not_the_engines_timeout(session, sid, fake_channel):
    """문은 잠긴 DB 를 BUSY_WAIT_MS 만 기다린다(엔진의 5초가 아니라). 풀로 돌려준 연결의 기다림은 원래대로다."""
    row, actor, now = arrange(session, sid, "pass")
    row_id = row.id
    session.rollback()
    with closing(sqlite3.connect(db_path(), isolation_level=None)) as holder:
        holder.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        out = await gate.dispatch("message", row_id, actor, now=now)
        waited = time.monotonic() - started
        holder.execute("ROLLBACK")

    assert (out.code, out.message) == ("duplicate", BUSY) and fake_channel.delivered == []
    assert gate.BUSY_WAIT_MS / 1000 * 0.8 <= waited < 3
    with db._engine.connect() as pooled:
        assert pooled.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000


async def test_short_database_wait_stays_on_the_gates_own_connection(session, sid, fake_channel, monkeypatch):
    """문이 줄인 DB 기다림(1초)은 문이 쓰는 그 연결에서만, 쓰는 동안만이다 — 풀에 쉬는 연결이 여럿이어도 문이 지나간 뒤(지나감·
    걸림·없는 줄·잠금 실패 모두) 모든 연결이 앱의 기다림 그대로이고, 문과 상관없는 세션이 잠긴 DB 를 기다리는 시간도 그대로다."""
    connect(session)
    who = person(session, sid)
    ids = [message(session, who, body=f"물음 {i}").id for i in range(6)]
    session.commit()
    session.rollback()
    engine = create_engine(f"sqlite:///{db_path()}", connect_args={"timeout": 1.5}, hide_parameters=True)
    monkeypatch.setattr(db, "_engine", engine)

    def waits() -> list[int]:
        """풀의 연결들을 한꺼번에 꺼내 저마다의 기다림(ms)을 읽는다."""
        held = [engine.connect() for _ in range(max(3, engine.pool.checkedin()))]
        try:
            return [pooled.exec_driver_sql("PRAGMA busy_timeout").scalar() for pooled in held]
        finally:
            for pooled in held:
                pooled.close()

    try:
        assert set(waits()) == {1500}
        outs = await asyncio.gather(*(gate.dispatch("message", row_id, USER, now=WORK) for row_id in ids))
        assert sorted(o.code for o in outs) == ["accepted"] * 5 + ["limit_person"]  # commit 하는 두 길, 여러 연결에서
        assert (await gate.dispatch("message", 987654, USER, now=WORK)).code == "not_sendable"
        with closing(sqlite3.connect(db_path(), isolation_level=None)) as holder:
            holder.execute("BEGIN IMMEDIATE")
            assert (await gate.dispatch("message", ids[0], USER, now=WORK)).message == BUSY  # 잠금 실패
            started = time.monotonic()
            with Session(engine) as unrelated, pytest.raises(OperationalError):
                unrelated.execute(text("BEGIN IMMEDIATE"))
            assert time.monotonic() - started >= 1.3  # 문의 1초가 아니라 엔진의 1.5초
            holder.execute("ROLLBACK")
        assert set(waits()) == {1500}
    finally:
        engine.dispose()


async def test_cancel_while_deciding_does_not_leave_a_claimed_row(session, sid, fake_channel):
    """판정이 (스레드에서) 도는 동안 부른 쪽이 취소됐다 → 차지한 줄이 통로 호출도 결과도 없이 sending 으로 남지 않는다:
    통로를 부르지 않았으니 failed(가지 않았음이 확실)로 닫고 취소를 다시 올린다."""
    row, actor, now = arrange(session, sid, "pass")
    row_id = row.id
    session.rollback()
    with closing(sqlite3.connect(db_path(), isolation_level=None)) as holder:
        holder.execute("BEGIN IMMEDIATE")
        task = asyncio.create_task(gate.dispatch("message", row_id, actor, now=now))
        await asyncio.sleep(0.1)  # 문은 지금 스레드에서 쓰기 잠금을 기다린다
        task.cancel()
        holder.execute("ROLLBACK")
        with pytest.raises(asyncio.CancelledError):
            await task

    row = reread(session, row)
    assert fake_channel.delivered == []
    assert (row.status, row.fail_reason) == ("failed", gate.FAIL_TEXT["cancelled_before_send"])
    assert trail(session, row) == [("channel_choice", "allowed"), ("delivery", "blocked")]
    assert_released()


def storm(rows, actor: Actor = USER, now: datetime = WORK) -> list[str]:
    """줄마다 진짜 스레드 하나(저마다 자기 이벤트 루프)에서 한꺼번에 문에 넣는다 → 판정 코드들."""
    gate_open = threading.Barrier(len(rows))
    codes: list[str | None] = [None] * len(rows)

    def one(index: int, kind: str, row_id: int) -> None:
        gate_open.wait(10)
        codes[index] = asyncio.run(gate.dispatch(kind, row_id, actor, now=now)).code

    threads = [threading.Thread(target=one, args=(i, kind_of(row), row.id)) for i, row in enumerate(rows)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert None not in codes, codes
    return codes


@pytest.mark.parametrize("channel", ["sms", "call"])
def test_threads_racing_for_one_row_deliver_once(session, sid, fake_channel, channel):
    row, actor, now = arrange(session, sid, "pass", channel)
    session.rollback()

    codes = storm([row] * 6, actor, now)

    assert len(fake_channel.delivered) == 1 and codes.count("accepted" if channel == "sms" else "queued") == 1
    assert set(codes) <= {"accepted", "queued", "duplicate", "not_sendable"}
    assert_released()


def test_threads_racing_with_the_same_text_send_one(session, sid, fake_channel):
    connect(session)
    who = person(session, sid)
    rows = [message(session, who) for _ in range(6)]
    session.commit()

    codes = storm(rows)

    assert len(fake_channel.delivered) == 1 and sorted(codes) == ["accepted"] + ["duplicate"] * 5


def test_threads_racing_for_the_last_slot_send_one(session, sid, fake_channel):
    connect(session, limits_json={"per_contact_sms_daily": 1})
    who = person(session, sid)
    rows = [message(session, who, body=f"물음 {i}") for i in range(6)]
    session.commit()

    codes = storm(rows)

    assert len(fake_channel.delivered) == 1 and codes.count("accepted") == 1
    assert set(codes) <= {"accepted", "limit_person", "duplicate"}  # duplicate 는 DB 를 기다리다 「잠시 뒤 다시」


def test_threads_racing_calls_to_one_person_place_one(session, sid, fake_channel):
    connect(session)
    who = person(session, sid)
    rows = [call(session, who, purpose_key=f"purpose-{i}") for i in range(6)]
    session.commit()

    codes = storm(rows)

    assert len(fake_channel.delivered) == 1 and sorted(codes) == ["duplicate"] * 5 + ["queued"]


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
