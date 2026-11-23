"""나가는 문(Task 65) — 답과 되풀이: 답 유예(30분), 자동 답 상한·같은 글 두 번, 수신 거부 확인 한 번,
통화 중 전환이 묻는 may_reach(차례 1·2만), 받지 않은 전화의 한 번뿐인 다시 걸기(after_no_answer).

도우미와 가상 값은 test_gate.py 것을 쓴다(번호·키는 모두 가상).
"""

import inspect
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine

from app import db
from app.outreach.harness import events, gate
from app.outreach.harness.types import Ref
from app.store.tables_outreach import (
    BlockedNumber,
    Contact,
    DoNotContactNumber,
    OutreachCall,
)
from app.store.timeutil import as_utc
from tests import schedules
from tests.outreach.harness.test_gate import (
    AGENT,
    BODY,
    KST,
    MONDAY,
    OFF,
    OTHER_PHONE,
    PHONE,
    SYSTEM,
    USER,
    WORK,
    call,
    connect,
    db_path,
    message,
    person,
    reread,
    send,
    trail,
)
from tests.outreach_doubles import SENTINEL_PHONE

DELEGATED = {"agent_sms": "delegate", "agent_kakao": "delegate", "agent_call": "delegate"}


def inbound(session, who=None, *, ago: timedelta, now: datetime = OFF, **over):
    """상대가 보낸 문자 한 건(now 보다 ago 앞에 받음)."""
    values = {"direction": "in", "origin": "peer", "status": "received", "body": "내일 타설 몇 시인가요",
              "created_at": now - ago, **over}
    return message(session, who, **values)


def auto(session, who, when: datetime, text: str, kind: str = "auto_reply"):
    """앞서 나간 자동 답 한 건."""
    return message(session, who, kind=kind, origin="agent", status="accepted", claimed_at=when, body=text)


# ── 답 유예 ──────────────────────────────────────────────────────────


async def test_reply_within_30_minutes_skips_hours(session, sid, fake_channel):
    """받은 지 29분 → 근무시간 밖이어도 나간다. 건너뛴 것은 판정 앞의 노트로 남는다."""
    connect(session)
    who = person(session, sid)
    reply = message(session, who, reply_to_id=inbound(session, who, ago=timedelta(minutes=29)).id)
    session.commit()

    out = await send(reply, USER, OFF)

    assert out.code == "accepted" and len(fake_channel.delivered) == 1
    assert trail(session, reply) == [("reply_within_grace", "noted"), ("channel_choice", "allowed"), ("delivery", "allowed")]


@pytest.mark.parametrize("minutes,code", [(29, "accepted"), (30, "scheduled"), (31, "scheduled")])
async def test_reply_exemption_ends_at_30_minutes(session, sid, fake_channel, minutes, code):
    connect(session)
    who = person(session, sid)
    reply = message(session, who, reply_to_id=inbound(session, who, ago=timedelta(minutes=minutes)).id)
    session.commit()

    out = await send(reply, USER, OFF)

    assert out.code == code
    if code == "scheduled":
        assert (out.rule, out.scheduled_at) == (3, MONDAY) and trail(session, reply) == [("working_hours", "blocked")]


@pytest.mark.parametrize("started_by,code", [("them", "accepted"), ("our_request", "scheduled")])
async def test_grace_is_for_conversations_they_started_not_for_answers_to_our_request(session, sid, fake_channel,
                                                                                    started_by, code):
    """설계: 30분 유예는 상대가 먼저 보낸 대화에만. 상대가 19:00 에 먼저 보냄 → 우리 19:10 답은 나감. 우리 09:00 요청에 19:00 에
    온 답 → 우리 19:10 답은 다음 근무 시작(월 08:00)으로 예약. 「우리 요청에 온 답」은 Task 67 의 물려받기 규칙과 같다(받은 줄이
    가리키는 줄이 우리가 보낸 같은 일정의 글 있는 메시지)."""
    connect(session)
    who = person(session, sid)
    ours = message(session, who, status="accepted", body="토요일 6명 가능하신가요", claimed_at=OFF.replace(hour=9),
                   created_at=OFF.replace(hour=9)) if started_by == "our_request" else None
    asked = inbound(session, who, ago=timedelta(minutes=10), now=OFF + timedelta(minutes=10),
                    reply_to_id=ours.id if ours is not None else None)
    reply = message(session, who, body="확인했습니다", reply_to_id=asked.id)
    session.commit()

    out = await send(reply, USER, OFF + timedelta(minutes=10))

    assert out.code == code
    if code == "scheduled":
        assert (out.rule, out.scheduled_at) == (3, MONDAY) and trail(session, reply) == [("working_hours", "blocked")]
        assert fake_channel.delivered == []
    else:
        assert trail(session, reply)[0] == ("reply_within_grace", "noted")


@pytest.mark.parametrize(("ours_kind", "code"), [("auto_reply", "accepted"), ("notice", "accepted"),
                                               ("dnc_confirm", "accepted"), ("normal_reply", "scheduled")])
async def test_their_conversation_keeps_grace_through_our_own_replies(session, sid, fake_channel, ours_kind, code):
    """판정(11-24): 상대가 19:00 에 먼저 보냄 → 우리 답 19:02 → 상대가 19:05 에 다시 → 우리 19:07 답도 유예로 나간다 — 우리 자동 답·고정
    안내·확인 문자는 「우리 요청」이 아니다(만들 때 적힌 kind 로 가린다). 사람이 쓰거나 고친 보통 글(kind normal)은 만든 길을 알 표시가
    없어 요청으로 본다(닫힌 쪽 — 예약)."""
    connect(session)
    who = person(session, sid)
    first = inbound(session, who, ago=timedelta(minutes=7), now=OFF + timedelta(minutes=7))
    kind = "normal" if ours_kind == "normal_reply" else ours_kind
    ours = message(session, who, kind=kind, origin="user" if kind == "normal" else "agent", status="accepted",
                   body="네 확인했습니다", reply_to_id=first.id, claimed_at=OFF + timedelta(minutes=2),
                   created_at=OFF + timedelta(minutes=2))
    again = inbound(session, who, ago=timedelta(minutes=2), now=OFF + timedelta(minutes=7), body="그럼 몇 시요?",
                    reply_to_id=ours.id)
    reply = message(session, who, body="담당자가 알려드리겠습니다", reply_to_id=again.id)
    session.commit()

    out = await send(reply, USER, OFF + timedelta(minutes=7))

    assert out.code == code
    assert (trail(session, reply)[0] == ("reply_within_grace", "noted")) is (code == "accepted")


async def test_answer_to_our_callback_is_an_answer_to_our_request(session, sid, fake_channel):
    """금 09:00 우리 요청 → 「월요일에 다시 연락 주세요」 → 월 08:00 다시 연락 줄(우리 요청 글을 물려받음, reply_to_id 는 상대 글) →
    월 19:00 상대 답 → 우리 19:10 답은 유예 없이 다음 근무 시작(화 08:00)으로 예약."""
    connect(session)
    who = person(session, sid)
    friday = OFF.replace(hour=9)
    request = message(session, who, status="accepted", body="토요일 6명 가능하신가요", claimed_at=friday, created_at=friday)
    later = inbound(session, who, ago=timedelta(minutes=0), now=friday + timedelta(minutes=30), body="월요일에 다시 연락 주세요",
                    reply_to_id=request.id)
    callback = message(session, who, status="accepted", origin="agent", origin_name="AI 비서", body=request.body,
                       reply_to_id=later.id, claimed_at=MONDAY, created_at=friday + timedelta(minutes=31))
    answer = inbound(session, who, ago=timedelta(minutes=10), now=MONDAY.replace(hour=19, minute=10), body="네 6명 갑니다",
                     reply_to_id=callback.id)
    reply = message(session, who, body="확인했습니다", reply_to_id=answer.id)
    session.commit()

    out = await send(reply, USER, MONDAY.replace(hour=19, minute=10))

    assert (out.code, out.scheduled_at) == ("scheduled", MONDAY + timedelta(days=1)) and fake_channel.delivered == []


@pytest.mark.parametrize("request_kind", ["empty_body", "other_schedule", "inbound"])
async def test_grace_stays_when_there_is_no_request_of_ours_to_inherit(session, sid, fake_channel, request_kind):
    """받은 줄이 가리키는 것이 물려받을 우리 요청이 아니면(글 없음 · 다른 일정 · 우리 글이 아님) 상대가 먼저 보낸 것으로 본다."""
    connect(session)
    who = person(session, sid)
    pointed = {
        "empty_body": lambda: message(session, who, status="accepted", body="  ", created_at=OFF.replace(hour=9)),
        "other_schedule": lambda: message(session, who, status="accepted", schedule_id=sid + 1000,
                                          created_at=OFF.replace(hour=9)),
        "inbound": lambda: inbound(session, who, ago=timedelta(hours=2)),
    }[request_kind]()
    asked = inbound(session, who, ago=timedelta(minutes=10), reply_to_id=pointed.id)
    reply = message(session, who, body="확인했습니다", reply_to_id=asked.id)
    session.commit()

    assert (await send(reply, USER, OFF)).code == "accepted"


@pytest.mark.parametrize("grace,minutes,code", [(10, 9, "accepted"), (10, 11, "scheduled"), (0, 0, "scheduled")])
async def test_reply_grace_comes_from_the_limits(session, sid, fake_channel, grace, minutes, code):
    connect(session, limits_json={"reply_grace_minutes": grace})
    who = person(session, sid)
    reply = message(session, who, reply_to_id=inbound(session, who, ago=timedelta(minutes=minutes)).id)
    session.commit()

    assert (await send(reply, USER, OFF)).code == code


@pytest.mark.parametrize("case", ["no_such_row", "our_own_message", "another_number", "from_the_future", "sent_long_ago"])
async def test_grace_needs_a_recent_inbound_from_that_very_number(session, sid, fake_channel, case):
    """reply_to_id 만 달았다고 근무시간을 건너뛰지 못한다 — 그 번호가 방금 보낸 받은 문자여야 한다."""
    connect(session)
    who, other = person(session, sid), person(session, sid, OTHER_PHONE, name="이철근")
    recent = timedelta(minutes=5)
    target = {
        "no_such_row": lambda: 987654,
        "our_own_message": lambda: message(session, who, status="accepted", created_at=OFF - recent).id,
        "another_number": lambda: inbound(session, other, ago=recent).id,
        "from_the_future": lambda: inbound(session, who, ago=-recent).id,
        "sent_long_ago": lambda: inbound(session, who, ago=recent, sent_at=OFF - timedelta(hours=2)).id,  # 늦게 읽어 온 문자
    }[case]()
    reply = message(session, who, reply_to_id=target)
    session.commit()

    assert (await send(reply, USER, OFF)).code == "scheduled" and fake_channel.delivered == []


async def test_reply_to_an_unknown_number_gets_the_same_grace(session, sid, fake_channel):
    """주소록에 없는 번호의 문자에 가는 고정 안내 — 번호로 견준다(연락처가 없어도 같다)."""
    connect(session, **DELEGATED)
    asked = inbound(session, None, ago=timedelta(minutes=3), peer_number=PHONE)
    notice = message(session, peer_number=PHONE, kind="notice", origin="agent", reply_to_id=asked.id)
    session.commit()

    assert (await send(notice, AGENT, OFF)).code == "accepted"


async def test_grace_skips_only_working_hours(session, sid, fake_channel):
    """답 유예는 근무시간만 건너뛴다 — 권한은 그대로. 위임 없는 에이전트는 권한을 근무시간보다 먼저 보므로(Task 81 고침 1) 유예
    노트 없이 permission 하나. 근무 중이면 노트가 없다."""
    connect(session)
    who = person(session, sid)
    asked = inbound(session, who, ago=timedelta(minutes=3))
    reply = message(session, who, origin="agent", reply_to_id=asked.id)
    daytime = message(session, who, body="근무 중에 보내는 답", reply_to_id=inbound(session, who, ago=timedelta(minutes=3), now=WORK).id)
    session.commit()

    out = await send(reply, AGENT, OFF)

    assert (out.code, out.rule) == ("needs_approval", 5) and fake_channel.delivered == []
    assert trail(session, reply) == [("permission", "blocked")]
    assert (await send(daytime, USER, WORK)).code == "accepted"
    assert trail(session, daytime) == [("channel_choice", "allowed"), ("delivery", "allowed")]


# ── 자동 답 ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("case,code", [
    ("hour_5th", "accepted"), ("hour_6th", "limit_person"), ("day_20th", "accepted"), ("day_21st", "limit_person"),
    ("notice_2nd", "limit_person"), ("notice_next_day", "accepted"),
])
async def test_auto_reply_caps(session, sid, fake_channel, case, code):
    """한 번호에 자동 답은 한 시간 5번·하루 20번까지(6번째·21번째는 limit_person), 고정 안내(notice)는 하루 한 번."""
    connect(session, **DELEGATED)
    who = person(session, sid)
    kind = "notice" if case.startswith("notice") else "auto_reply"
    dawn = datetime(2026, 11, 27, 1, 0, tzinfo=KST)  # 오늘이지만 한 시간보다 앞
    before = {
        "hour_5th": [WORK - timedelta(minutes=50 - i) for i in range(4)],
        "hour_6th": [WORK - timedelta(minutes=50 - i) for i in range(5)],
        "day_20th": [dawn + timedelta(minutes=i) for i in range(19)],
        "day_21st": [dawn + timedelta(minutes=i) for i in range(20)],
        "notice_2nd": [WORK - timedelta(hours=3)],
        "notice_next_day": [WORK - timedelta(days=1)],
    }[case]
    for i, when in enumerate(before):
        auto(session, who, when, f"앞선 자동 답 {i}", kind)
    auto(session, who, dawn - timedelta(hours=2), "어젯밤의 자동 답")  # 어제(서울 날짜) 것은 오늘 셈에 들지 않는다
    row = message(session, who, kind=kind, origin="agent", body="새 자동 답")
    session.commit()

    out = await send(row, AGENT, WORK)

    assert out.code == code and out.rule == (4 if code == "limit_person" else None)
    assert len(fake_channel.delivered) == (code == "accepted")


async def test_auto_replies_use_their_own_caps_not_the_per_person_cap(session, sid, fake_channel):
    """자동 답은 자동 답 상한을 따른다(한 사람 하루 문자 상한 5가 아니라). 사람이 보내는 보통 문자는 그 상한을 그대로 받는다."""
    connect(session, limits_json={"auto_reply_hourly": 9}, **DELEGATED)
    who = person(session, sid)
    for i in range(5):
        auto(session, who, WORK - timedelta(minutes=50 - i), f"자동 답 {i}")
    sixth = message(session, who, kind="auto_reply", origin="agent", body="여섯째 자동 답")
    normal = message(session, who, body="사람이 보내는 글")
    session.commit()

    assert (await send(sixth, AGENT, WORK)).code == "accepted"
    assert (await send(normal, USER, WORK)).code == "limit_person"


async def test_same_reply_twice_is_blocked(session, sid, fake_channel):
    """자동 답의 글이 그 번호에 마지막으로 나간 자동 답과 같으면 보내지 않는다(기계끼리 주고받기)."""
    connect(session, **DELEGATED)
    who = person(session, sid)
    auto(session, who, WORK - timedelta(minutes=40), "먼저 나간 답")
    auto(session, who, WORK - timedelta(minutes=30), "타설은 11월 30일입니다.")
    same = message(session, who, kind="auto_reply", origin="agent", body=" 타설은 11월 30일입니다.\n")
    older = message(session, who, kind="auto_reply", origin="agent", body="먼저 나간 답")
    by_person = message(session, who, body="타설은 11월 30일입니다.")
    session.commit()

    out = await send(same, AGENT, WORK)

    assert (out.code, out.rule) == ("duplicate", 6)
    assert reread(session, same).status == "draft" and fake_channel.delivered == []
    assert (await send(by_person, USER, WORK)).code == "accepted"  # 사람이 쓴 보통 문자에는 이 규칙이 없다
    assert (await send(older, AGENT, WORK)).code == "accepted"  # 마지막 것과만 견준다


@pytest.mark.parametrize("kind", ["auto_reply", "notice"])
async def test_a_person_cannot_send_a_row_marked_as_an_automatic_reply(session, sid, fake_channel, kind):
    """kind 는 상한을 바꾼다(자동 답은 사람당 상한 대신 자동 답 상한) — 그래서 자동 답·고정 안내 줄은 에이전트·일꾼의 길로만
    나간다. 사람이 보내거나 승인할 글은 보통 글(kind normal)로 만든다."""
    connect(session, **DELEGATED)
    row = message(session, person(session, sid), kind=kind, origin="agent")
    session.commit()

    out = await send(row, USER)

    assert (out.code, out.rule) == ("not_sendable", 0) and fake_channel.delivered == []
    assert (await send(row, AGENT)).code == "accepted"


# ── 수신 거부 확인 ────────────────────────────────────────────────────


async def test_dnc_confirm_passes_once(session, sid, fake_channel):
    """수신 거부로 표시한 뒤의 확인 문자(kind dnc_confirm)는 한 번만 지나간다. 그 밖의 글은 막힌다."""
    connect(session)
    session.add(DoNotContactNumber(number=PHONE, reason="문자로 수신 거부", created_at=WORK - timedelta(minutes=1)))
    confirm = message(session, peer_number=PHONE, kind="dnc_confirm", origin="agent", body=gate.DNC_CONFIRM_TEXT)
    again = message(session, peer_number=PHONE, kind="dnc_confirm", origin="agent", body=gate.DNC_CONFIRM_TEXT)
    normal = message(session, peer_number=PHONE, body="그래도 보내는 글")
    session.commit()

    assert (await send(confirm)).code == "accepted"
    for row in (again, normal):
        out = await send(row, USER, WORK + timedelta(minutes=5))
        assert (out.code, out.rule) == ("do_not_contact", 2)
    assert [d.row_id for d in fake_channel.delivered] == [confirm.id]


async def test_dnc_confirm_passes_again_only_after_a_new_mark(session, sid, fake_channel):
    """관리자가 풀었다가 다시 수신 거부가 되면 그 표시에 대한 확인이 한 번 더 나간다(앞 표시 때의 확인은 세지 않는다)."""
    connect(session)
    message(session, peer_number=PHONE, kind="dnc_confirm", origin="agent", status="accepted",
            claimed_at=WORK - timedelta(days=3), body=gate.DNC_CONFIRM_TEXT)
    session.add(DoNotContactNumber(number=PHONE, reason="다시 수신 거부", created_at=WORK - timedelta(minutes=1)))
    confirm = message(session, peer_number=PHONE, kind="dnc_confirm", origin="agent", body=gate.DNC_CONFIRM_TEXT)
    session.commit()

    assert (await send(confirm)).code == "accepted"


async def test_dnc_confirm_for_a_contact_mark_passes_once(session, sid, fake_channel):
    """연락처 줄의 표시만 있는(번호 기준 줄이 없는) 수신 거부 — 확인은 그 번호에 한 번."""
    connect(session)
    who = person(session, sid, do_not_contact=True)
    rows = [message(session, who, kind="dnc_confirm", origin="agent", body=gate.DNC_CONFIRM_TEXT) for i in range(2)]
    session.commit()

    assert [(await send(row)).code for row in rows] == ["accepted", "do_not_contact"]


@pytest.mark.parametrize("text", [BODY, "수신 거부로 처리했습니다. 그런데 내일 타설은 가능하신가요", ""])
async def test_dnc_confirm_must_be_the_fixed_text(session, sid, fake_channel, text):
    """kind dnc_confirm 이라고 적었다고 아무 글이나 수신 거부한 번호에 가지 않는다 — 문이 정해 둔 확인 글과 같아야 한다."""
    connect(session)
    session.add(DoNotContactNumber(number=PHONE, reason="문자로 수신 거부", created_at=WORK - timedelta(minutes=1)))
    row = message(session, peer_number=PHONE, kind="dnc_confirm", origin="agent", body=text)
    proper = message(session, peer_number=PHONE, kind="dnc_confirm", origin="agent", body=f" {gate.DNC_CONFIRM_TEXT}\n")
    session.commit()

    out = await send(row)

    assert (out.code, out.rule) == ("not_sendable", 0) and fake_channel.delivered == []
    assert (await send(proper)).code == "accepted"  # 막힌 시도는 「한 번」을 쓰지 않는다


async def test_dnc_confirm_takes_every_other_check(session, sid, fake_channel):
    """확인 문자가 건너뛰는 것은 수신 거부 하나뿐 — 관리자 차단과 시험 모드는 그대로다."""
    conn = connect(session)
    session.add(DoNotContactNumber(number=PHONE, reason="문자로 수신 거부", created_at=WORK - timedelta(minutes=1)))
    session.add(BlockedNumber(number=PHONE, reason="요청", created_by="관리자"))
    blocked = message(session, peer_number=PHONE, kind="dnc_confirm", origin="agent", body=gate.DNC_CONFIRM_TEXT)
    session.commit()
    assert (await send(blocked)).code == "blocked_number"

    conn.test_mode = True
    tested = message(session, peer_number=PHONE, kind="dnc_confirm", origin="agent", body=gate.DNC_CONFIRM_TEXT)
    session.commit()
    assert (await send(tested)).code == "blocked_test" and fake_channel.delivered == []


# ── may_reach ────────────────────────────────────────────────────────


def test_may_reach_covers_only_rules_1_and_2(session, sid):
    """통화 중 전환이 묻는다: 시험 모드·차단·수신 거부만 본다. 근무시간·상한·권한·연결 상태는 보지 않는다."""
    assert list(inspect.signature(gate.may_reach).parameters) == ["session", "number"]
    assert gate.may_reach(session, PHONE) is False  # 기본 연결이 없으면 어디에도 닿을 수 없다

    conn = connect(session, status="failed", limits_json={"daily_calls_total": 0, "per_contact_calls_daily": 0})
    person(session, sid, hours_json={"days": [], "start": "09:00", "end": "18:00"})
    assert gate.may_reach(session, PHONE) is True
    assert gate.may_reach(session, SENTINEL_PHONE) is True  # 꼴이 달라도 같은 번호
    assert gate.may_reach(session, "번호 아님") is False

    conn.test_mode = True
    assert gate.may_reach(session, PHONE) is False
    conn.allow_numbers_json = [SENTINEL_PHONE]
    assert gate.may_reach(session, PHONE) is True and gate.may_reach(session, OTHER_PHONE) is False

    conn.test_mode = False
    session.add(BlockedNumber(number=OTHER_PHONE, reason="요청", created_by="관리자"))
    session.flush()
    assert gate.may_reach(session, OTHER_PHONE) is False


def test_may_reach_ignores_non_text_values_in_the_allow_list(session, sid):
    connect(session, test_mode=True, allow_numbers_json=[None, 7, {"a": 1}, SENTINEL_PHONE])

    assert gate.may_reach(session, PHONE) is True and gate.may_reach(session, OTHER_PHONE) is False


def test_may_reach_follows_do_not_contact_by_number(session, sid):
    connect(session)
    person(session, schedules.store(session, schedules.sample()), do_not_contact=True)  # 다른 일정의 표시
    session.add(DoNotContactNumber(number=OTHER_PHONE, reason="문자로 수신 거부"))
    session.flush()

    assert gate.may_reach(session, PHONE) is False and gate.may_reach(session, OTHER_PHONE) is False
    assert gate.may_reach(session, "01000000177") is True


# ── 받지 않은 전화 ────────────────────────────────────────────────────


def _unanswered(session, sid, **over) -> OutreachCall:
    who = person(session, sid)
    return call(session, who, **{"status": "no_answer", "origin": "agent", "origin_name": "에이전트", "send_mode": "delegated",
                                 "purpose_key": "pour-3f", "questions_json": ["타설 가능한가요"], "avoid_json": ["단가"],
                                 "language": "vi", "voice_id": "voice-a", "activity_id": "A", "claimed_at": WORK, **over})


async def test_no_answer_retry_only_once_and_only_when_delegated(session, sid, fake_channel):
    """받지 않은 전화: 전화 권한이 위임이고 아직 쓰지 않았을 때만, 다음 근무 시간대에 한 번 — 새 줄로."""
    conn = connect(session)
    first = _unanswered(session, sid)
    session.commit()
    assert gate.after_no_answer(first.id, now=WORK) is None  # 「승인 받기」면 자동으로 다시 걸지 않는다

    conn.agent_call = "delegate"
    session.commit()
    retry_id = gate.after_no_answer(first.id, now=WORK)

    assert retry_id is not None and retry_id != first.id
    assert gate.after_no_answer(first.id, now=WORK) is None  # 한 번뿐
    retry = reread(session, session.get(OutreachCall, retry_id))
    assert (retry.status, as_utc(retry.scheduled_at)) == ("scheduled", MONDAY)  # 지금 근무 시간대가 아니라 그다음 것
    assert (retry.retry_of, retry.auto_retry_used, retry.send_mode, retry.origin) == (first.id, True, "delegated", "agent")
    assert (retry.schedule_id, retry.contact_id, retry.purpose, retry.purpose_key) == (
        first.schedule_id, first.contact_id, first.purpose, "pour-3f")
    assert (retry.questions_json, retry.avoid_json, retry.language, retry.voice_id, retry.activity_id) == (
        ["타설 가능한가요"], ["단가"], "vi", "voice-a", "A")
    assert retry.claimed_at is None and retry.direction == "out"
    assert reread(session, first).auto_retry_used is True and reread(session, first).status == "no_answer"
    assert trail(session, first) == [("no_answer_retry", "noted")]
    assert events.of(session, Ref("call", retry_id)) == []

    assert (await send(retry, SYSTEM, MONDAY)).code == "queued"  # 때가 되면 처음부터 다시 검사받고 나간다
    retry.status = "no_answer"
    session.commit()
    assert gate.after_no_answer(retry_id, now=MONDAY) is None  # 다시 건 것도 받지 않으면 그만


async def test_retry_is_rechecked_when_due(session, sid, fake_channel):
    """예약된 다시 걸기도 때가 되면 문을 처음부터 지난다 — 그 사이 위임이 꺼졌으면 걸지 않는다."""
    conn = connect(session, agent_call="delegate")
    first = _unanswered(session, sid)
    session.commit()
    retry = session.get(OutreachCall, gate.after_no_answer(first.id, now=WORK))
    conn.agent_call = "approve"
    session.commit()

    out = await send(retry, SYSTEM, MONDAY)

    assert out.code == "needs_approval" and fake_channel.delivered == []


@pytest.mark.parametrize("over", [
    {"status": "completed"}, {"status": "busy"}, {"status": "failed"}, {"status": "draft"}, {"direction": "in"},
    {"auto_retry_used": True},
])
def test_no_retry_for_calls_that_were_not_unanswered_outbound_calls(session, sid, over):
    connect(session, agent_call="delegate")
    row = _unanswered(session, sid, **over)
    session.commit()

    assert gate.after_no_answer(row.id, now=WORK) is None
    assert gate.after_no_answer(987654, now=WORK) is None
    session.expire_all()
    assert session.query(OutreachCall).count() == 1


def test_no_retry_when_there_is_no_next_working_window(session, sid):
    connect(session, agent_call="delegate")
    who = person(session, sid, hours_json={"days": [], "start": "09:00", "end": "18:00"})
    row = call(session, who, status="no_answer", send_mode="delegated")
    session.commit()

    assert gate.after_no_answer(row.id, now=WORK) is None
    assert reread(session, row).auto_retry_used is False and session.query(OutreachCall).count() == 1


def test_retry_after_an_off_hours_miss_waits_for_the_next_start(session, sid):
    """근무 밖에 끝난 통화(늦게 닫힌 줄)도 다음 근무 시작으로 — 지금 바로 걸지 않는다."""
    connect(session, agent_call="delegate")
    first = _unanswered(session, sid)
    session.commit()

    retry = session.get(OutreachCall, gate.after_no_answer(first.id, now=OFF))

    assert as_utc(retry.scheduled_at) == MONDAY


def test_automatic_redial_of_a_persons_call_is_recorded_as_automatic(session, sid):
    """사람이 건 통화의 자동 다시 걸기를 「사람이 건 것」으로 적지 않는다 — 시작한 쪽은 에이전트, 이름은 정해 둔 것."""
    connect(session, agent_call="delegate")
    first = _unanswered(session, sid, origin="user", origin_name="김공정", send_mode="manual")
    session.commit()

    retry = session.get(OutreachCall, gate.after_no_answer(first.id, now=WORK))

    assert (retry.origin, retry.origin_name, retry.send_mode, retry.approved_by) == (
        "agent", gate.AUTO_REDIAL_NAME, "delegated", None)
    assert as_utc(retry.created_at) == WORK


@pytest.mark.parametrize("meanwhile", ["person_redialled", "redial_did_not_connect", "nothing"])
async def test_due_automatic_redial_is_dropped_when_that_number_was_called_meanwhile(session, sid, fake_channel, meanwhile):
    """자동 다시 걸기를 예약한 뒤 그 번호로 전화가 한 번이라도 나갔으면(목적 손잡이가 달라도, 받지 않았어도) 때가 돼도 걸지
    않는다 — 기록만 남긴다."""
    connect(session, agent_call="delegate")
    first = _unanswered(session, sid)
    session.commit()
    retry = session.get(OutreachCall, gate.after_no_answer(first.id, now=WORK))
    who = session.get(Contact, first.contact_id)
    if meanwhile != "nothing":
        call(session, who, purpose_key="", claimed_at=WORK + timedelta(minutes=5),
             status="completed" if meanwhile == "person_redialled" else "no_answer")
    session.commit()

    out = await send(retry, SYSTEM, MONDAY)

    if meanwhile == "nothing":
        assert out.code == "queued" and len(fake_channel.delivered) == 1
    else:
        assert (out.code, out.rule) == ("duplicate", 6) and fake_channel.delivered == []
        retry = reread(session, retry)
        assert retry.status == "draft" and retry.fail_reason and trail(session, retry) == [("duplicate", "blocked")]


def test_no_retry_when_the_stored_hours_are_malformed(session, sid):
    connect(session, agent_call="delegate")
    who = person(session, sid, hours_json={"days": [0], "start": "아홉 시", "end": "18:00"})
    row = call(session, who, status="no_answer", send_mode="delegated")
    session.commit()

    assert gate.after_no_answer(row.id, now=WORK) is None
    assert reread(session, row).auto_retry_used is False


def test_no_retry_and_no_error_when_the_database_is_busy(session, sid, monkeypatch):
    """다른 쓰기가 DB 를 쥐고 있으면 예외 없이 None — 「한 번」을 쓰지 않았으므로 뒤에 다시 부르면 된다."""
    connect(session, agent_call="delegate")
    first = _unanswered(session, sid)
    session.commit()
    first_id = first.id
    session.rollback()
    engine = create_engine(f"sqlite:///{db_path()}", connect_args={"timeout": 0.1}, hide_parameters=True)
    monkeypatch.setattr(db, "_engine", engine)
    try:
        with closing(sqlite3.connect(db_path(), isolation_level=None)) as holder:
            holder.execute("BEGIN IMMEDIATE")
            assert gate.after_no_answer(first_id, now=WORK) is None
            holder.execute("ROLLBACK")
        retry_id = gate.after_no_answer(first_id, now=WORK)
    finally:
        engine.dispose()
    assert retry_id is not None and session.query(OutreachCall).count() == 2
