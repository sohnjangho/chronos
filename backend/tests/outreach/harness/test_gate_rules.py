"""나가는 문(Task 65) — 차례마다의 규칙: 앞 확인, 차단·수신 거부, 근무시간, 상한, 권한, 중복, 채널 고르기.

도우미와 가상 값은 test_gate.py 것을 쓴다(번호·키는 모두 가상).
"""

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.outreach.harness import events, gate, registry
from app.outreach.harness.types import Ref
from app.store import outreach
from app.store.tables_outreach import DoNotContactNumber, KakaoTemplate
from app.store.timeutil import as_utc
from tests import schedules
from tests.harness_doubles import FakeChannel
from tests.outreach.harness.test_gate import (
    AGENT,
    BODY,
    BUSY,
    CASES,
    KST,
    LANDLINE,
    MONDAY,
    OFF,
    OTHER_PHONE,
    PHONE,
    SYSTEM,
    USER,
    WORK,
    arrange,
    call,
    connect,
    earlier,
    expected,
    message,
    person,
    reread,
    row_for,
    send,
    trail,
)

DELEGATED = {"agent_sms": "delegate", "agent_kakao": "delegate", "agent_call": "delegate"}


# ── 0 앞 확인 ────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", [None, "failed", "unknown"])
async def test_missing_or_unchecked_connection_is_not_ready(session, sid, fake_channel, status):
    if status is not None:
        connect(session, status=status)
    row = message(session, person(session, sid), status="scheduled", scheduled_at=WORK, send_mode="manual")
    session.commit()

    out = await send(row)

    assert (out.code, out.rule) == ("not_ready", 0) and fake_channel.delivered == []
    row = reread(session, row)
    assert (row.status, row.scheduled_at, row.send_mode) == ("draft", None, None) and row.fail_reason


@pytest.mark.parametrize("channel", ["sms", "call"])
async def test_unregistered_channel_is_not_ready(session, sid, monkeypatch, channel):
    """통로가 아직 등록되지 않았다(가짜도 없음) → 차지하기 전에 멈춘다(줄이 「보내는 중」으로 남지 않는다)."""
    monkeypatch.setattr(registry, "_CHANNELS", {})  # 뒤 작업이 진짜 통로를 등록한 뒤에도 「아무것도 없음」을 본다
    monkeypatch.setattr(registry, "_PINNED", [])
    connect(session)
    row = row_for(session, channel, person(session, sid))
    session.commit()

    out = await send(row)

    assert (out.code, out.rule) == ("not_ready", 0)
    row = reread(session, row)
    assert row.status == "draft" and row.claimed_at is None and trail(session, row) == [("precheck", "blocked")]


async def test_contact_of_another_schedule_is_not_sendable(session, sid, fake_channel):
    """줄과 연락처가 같은 일정 것이어야 한다(프로젝트 격리)."""
    connect(session)
    elsewhere = person(session, schedules.store(session, schedules.sample()))
    row = message(session, schedule_id=sid, contact_id=elsewhere.id)
    gone = message(session, schedule_id=sid, contact_id=987654)
    session.commit()

    for each in (row, gone):
        out = await send(each)
        assert (out.code, out.rule) == ("not_sendable", 0)
    assert fake_channel.delivered == []


@pytest.mark.parametrize("channel", ["sms", "kakao", "call"])
@pytest.mark.parametrize("flaw", ["no_number", "invalid_flag", "not_a_number", "premium", "flag_off"])
async def test_number_must_be_present_valid_and_reachable(session, sid, fake_channel, channel, flaw):
    connect(session)
    who = person(session, sid, **{
        "no_number": {"phone": None}, "invalid_flag": {"phone_invalid": True}, "not_a_number": {"phone": "0101234"},
        "premium": {"phone": "06000000199"}, "flag_off": {f"can_{channel}": False},
    }[flaw])
    row = row_for(session, channel, who)
    session.commit()

    out = await send(row)

    assert (out.code, out.rule) == ("not_sendable", 0) and fake_channel.delivered == []
    row = reread(session, row)
    assert row.status == "draft" and row.fail_reason and PHONE[-4:] not in row.fail_reason


async def test_peer_number_row_needs_a_real_number(session, sid, fake_channel):
    connect(session)
    rows = [message(session, peer_number=None), message(session, peer_number="번호 아님"), call(session, peer_number=None)]
    session.commit()

    assert [(await send(row)).code for row in rows] == ["not_sendable"] * 3
    assert fake_channel.delivered == []


async def test_landline_cannot_get_sms(session, sid, fake_channel):
    """02 번호 연락처: 문자·카카오톡 줄은 not_sendable(휴대전화만), 전화 줄은 지나간다."""
    connect(session)
    who = person(session, sid, LANDLINE)
    rows = {channel: row_for(session, channel, who) for channel in ("sms", "kakao", "call")}
    session.commit()

    assert (await send(rows["sms"])).code == "not_sendable"
    assert (await send(rows["kakao"])).code == "not_sendable"
    assert (await send(rows["call"])).code == "queued"
    assert [d.channel for d in fake_channel.delivered] == ["call"]


async def test_kakao_row_that_would_go_as_sms_needs_the_sms_flag(session, sid, fake_channel):
    """카카오톡은 받지만 문자는 받지 않는 사람 — 카카오톡이 잠겨 문자로 나갈 줄이면 보내지 않는다."""
    connect(session)
    row = message(session, person(session, sid, can_sms=False), channel="kakao")
    session.commit()

    assert (await send(row)).code == "not_sendable" and fake_channel.delivered == []


async def test_empty_text_is_not_sendable(session, sid, fake_channel):
    connect(session)
    row = message(session, person(session, sid), body="  \n ")
    session.commit()

    out = await send(row)

    assert (out.code, out.rule) == ("not_sendable", 0) and fake_channel.delivered == []


@pytest.mark.parametrize("channel,status", [
    *[("sms", s) for s in ("accepted", "delivered", "failed", "unconfirmed", "blocked_test", "received")],
    *[("call", s) for s in ("completed", "no_answer", "busy", "failed", "blocked_test", "rejected", "missed")],
])
async def test_finished_rows_are_not_sendable_and_stay_as_they_are(session, sid, fake_channel, channel, status):
    connect(session)
    row = row_for(session, channel, person(session, sid), status=status, fail_reason="앞선 까닭")
    session.commit()

    for actor in (USER, AGENT, SYSTEM):
        out = await send(row, actor)
        assert (out.code, out.rule) == ("not_sendable", 0)
    row = reread(session, row)
    assert (row.status, row.fail_reason) == (status, "앞선 까닭") and fake_channel.delivered == []


@pytest.mark.parametrize("channel,status", [("sms", "sending"), ("call", "queued"), ("call", "dialing"), ("call", "in_call")])
async def test_row_already_on_its_way_is_a_duplicate_not_already_sent(session, sid, fake_channel, channel, status):
    connect(session, test_mode=True)  # 다른 차례에 걸릴 입력이어도 나가는 중인 줄은 건드리지 않는다
    row = row_for(session, channel, person(session, sid), status=status, claimed_at=WORK)
    session.commit()

    out = await send(row)

    assert (out.code, out.rule, out.message) == ("duplicate", 6, BUSY)
    assert reread(session, row).status == status and fake_channel.delivered == []
    assert trail(session, row) == [("duplicate", "blocked")]


# ── 2 차단·수신 거부 ──────────────────────────────────────────────────


async def test_do_not_contact_follows_the_number_across_projects(session, sid, fake_channel):
    """한 프로젝트에서 수신 거부가 되면 그 번호는 어느 프로젝트에서도 나가지 않는다(문자도 전화도)."""
    connect(session)
    person(session, sid, do_not_contact=True, hidden=True)
    there = person(session, schedules.store(session, schedules.sample()))  # 같은 번호, 다른 일정, 표시 없음
    rows = [message(session, there), call(session, there), message(session, peer_number=PHONE)]
    session.commit()

    for row in rows:
        out = await send(row)
        assert (out.code, out.rule) == ("do_not_contact", 2)
        assert reread(session, row).status == "draft"
    assert fake_channel.delivered == []


async def test_number_based_do_not_contact_blocks_without_any_contact_mark(session, sid, fake_channel):
    connect(session)
    session.add(DoNotContactNumber(number=PHONE, reason="문자로 수신 거부"))
    row = message(session, person(session, sid))
    session.commit()

    assert (await send(row)).code == "do_not_contact" and fake_channel.delivered == []


@pytest.mark.parametrize("answer,code", [(False, "accepted"), (True, "do_not_contact")])
async def test_do_not_contact_is_decided_only_by_number_store(session, sid, fake_channel, monkeypatch, answer, code):
    """문은 연락처 줄을 스스로 훑지 않는다 — store.outreach.is_do_not_contact 의 답을 그대로 따른다(한 번 묻는다)."""
    connect(session)
    row = message(session, person(session, sid, do_not_contact=not answer))  # 연락처 표시는 답과 반대로 둔다
    session.commit()
    asked = []

    def spy(_session, number):
        asked.append(number)
        return answer

    monkeypatch.setattr(outreach, "is_do_not_contact", spy)

    assert (await send(row)).code == code
    assert asked == [PHONE]


# ── 3 근무시간 ────────────────────────────────────────────────────────


async def test_off_hours_sms_is_scheduled_at_next_start(session, sid, fake_channel):
    """금요일 19시 → 월요일 08시로 예약(시간대가 붙은 KST 값). 차지하지 않았으므로 그날 셈에 들지 않는다."""
    row, actor, _ = arrange(session, sid, "pass")

    out = await send(row, actor, OFF)

    assert (out.code, out.rule) == ("scheduled", 3)
    assert out.scheduled_at == MONDAY and out.scheduled_at.utcoffset() == timedelta(hours=9)
    row = reread(session, row)
    assert as_utc(row.scheduled_at) == datetime(2026, 11, 30, 8, 0, tzinfo=KST)
    assert (row.status, row.send_mode, row.claimed_at, row.fail_reason) == ("scheduled", "manual", None, None)
    assert fake_channel.delivered == []


async def test_off_hours_call_is_blocked_and_offers_the_next_start(session, sid, fake_channel):
    """전화는 걸지 않고 예약도 하지 않는다(예약은 사람이 따로 누름) — 다음 근무 시작만 알려 준다."""
    row, actor, _ = arrange(session, sid, "pass", "call")

    out = await send(row, actor, OFF)

    assert (out.code, out.rule, out.scheduled_at) == ("blocked_hours", 3, MONDAY)
    row = reread(session, row)
    assert (row.status, row.scheduled_at, row.claimed_at) == ("blocked_hours", None, None)
    assert (await send(row, actor, MONDAY)).code == "queued"  # 근무시간에 다시 누르면 나간다
    assert trail(session, row) == [("working_hours", "blocked"), ("channel_choice", "allowed"), ("delivery", "allowed")]


async def test_the_persons_own_hours_decide(session, sid, fake_channel):
    """주말 오전만 일하는 사람 — 금요일 10시(프로젝트 근무시간)여도 예약된다."""
    connect(session)
    row = message(session, person(session, sid, hours_json={"days": [5, 6], "start": "09:00", "end": "12:00"}))
    session.commit()

    out = await send(row, USER, WORK)

    assert out.code == "scheduled" and out.scheduled_at == datetime(2026, 11, 28, 9, 0, tzinfo=KST)


@pytest.mark.parametrize("channel", ["sms", "kakao", "call"])
async def test_no_working_time_is_blocked_by_hours_not_an_error(session, sid, fake_channel, channel):
    """근무 시간대가 아예 없는 사람(NoWorkingTime) → 예외가 아니라 「근무시간으로 막힘」."""
    connect(session)
    row = row_for(session, channel, person(session, sid, hours_json={"days": [], "start": "09:00", "end": "18:00"}))
    session.commit()

    out = await send(row)

    assert (out.code, out.rule, out.scheduled_at) == ("blocked_hours", 3, None) and fake_channel.delivered == []
    row = reread(session, row)
    if channel == "call":
        assert row.status == "blocked_hours"
    else:
        assert (row.status, row.fail_reason) == ("draft", "근무시간을 찾을 수 없습니다")
    assert trail(session, row) == [("working_hours", "blocked")]


@pytest.mark.parametrize("change,code", [("delegation_off", "needs_approval"), ("dnc", "do_not_contact"),
                                         ("test_mode", "blocked_test"), ("none", "accepted")])
async def test_scheduled_row_is_rechecked_from_the_top_when_due(session, sid, fake_channel, change, code):
    """예약해 둔 뒤 설정이 달라졌다 — 때가 돼 일꾼이 다시 넣으면 처음부터 다시 보고, 통과하지 못하면 나가지 않는다."""
    conn = connect(session, **DELEGATED)
    who = person(session, sid)
    row = message(session, who, origin="agent")
    session.commit()
    assert (await send(row, AGENT, OFF)).code == "scheduled"
    assert reread(session, row).send_mode == "delegated"

    if change == "delegation_off":
        conn.agent_sms = "approve"
    elif change == "dnc":
        who.do_not_contact = True
    elif change == "test_mode":
        conn.test_mode = True
    session.commit()
    out = await send(row, SYSTEM, MONDAY)

    assert out.code == code and len(fake_channel.delivered) == (code == "accepted")
    row = reread(session, row)
    if change == "delegation_off":
        assert row.status == "draft" and "승인" in row.fail_reason
        assert trail(session, row) == [("working_hours", "blocked"), ("permission", "blocked")]


async def test_unapproved_agent_message_scheduled_off_hours_never_leaves(session, sid, fake_channel):
    """「승인 받기」인 에이전트의 글이 근무 밖이라 예약돼도(차례 3이 먼저) 때가 되면 권한에서 멈춘다 — 사람 승인 없이 나가지 않는다."""
    connect(session)
    row = message(session, person(session, sid), origin="agent")
    session.commit()

    assert (await send(row, AGENT, OFF)).code == "scheduled"
    out = await send(row, SYSTEM, MONDAY)

    assert (out.code, out.rule) == ("needs_approval", 5) and fake_channel.delivered == []
    assert reread(session, row).status == "draft"


# ── 4 상한 ────────────────────────────────────────────────────────────


async def test_limits_come_from_accessor(session, sid, fake_channel):
    """상한은 store.outreach.limits(conn) 에서 검사할 때마다 읽는다 — 설정을 바꾸면 다음 검사부터 바뀐다."""
    conn = connect(session, limits_json={"daily_sms_total": 2, "per_contact_sms_daily": 1})
    who, other = person(session, sid), person(session, sid, OTHER_PHONE, name="이철근")
    earlier(session, "sms", who)
    rows = [message(session, who, body=f"물음 {i}") for i in range(3)]
    session.commit()

    assert (await send(rows[0])).code == "limit_person"  # 한 사람 1건
    conn.limits_json = {"daily_sms_total": 2, "per_contact_sms_daily": 9}
    session.commit()
    assert (await send(rows[1])).code == "accepted"
    assert (await send(rows[2])).code == "limit_daily"  # 하루 2건(앞서 나간 것 + 방금)
    conn.limits_json = None
    late = message(session, other)
    session.commit()
    assert (await send(late)).code == "accepted"  # 기본값으로 돌아가면 지나간다


def test_gate_holds_no_limit_numbers():
    """gate.py·door.py 에 상한 숫자 상수가 없다. gate.py 의 숫자 상수는 DUPLICATE_WINDOW_S 하나뿐이고 그 밖에 상한 값 글자를
    쓰지 않는다. door.py 는 설정으로 바꾸는 상한 값(Limits 의 기본값)을 모듈 상수로 두지 않는다(동시 통화 한도 같은 다른 상수는 둔다)."""
    limit_values = {50, 10, 5, 2, 20, 30, 300, 120}
    assert gate.DUPLICATE_WINDOW_S == 120
    for name in ("gate.py", "door.py"):
        path = Path(gate.__file__).with_name(name)
        if not path.exists():  # door.py 는 Task 66 — 아직 없으면 건너뛴다
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {
            target.id: node.value.value
            for node in tree.body if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            for target in node.targets if isinstance(target, ast.Name)
            if type(node.value.value) in (int, float)
        }
        assert {key: value for key, value in constants.items() if value in limit_values} == (
            {"DUPLICATE_WINDOW_S": 120} if name == "gate.py" else {}), name
        if name == "gate.py":
            assert constants == {"DUPLICATE_WINDOW_S": 120}
            literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and type(n.value) in (int, float)]
            assert sorted(v for v in literals if v in limit_values) == [120]


async def test_yesterdays_sends_do_not_count_today(session, sid, fake_channel):
    connect(session, limits_json={"daily_sms_total": 1, "per_contact_sms_daily": 1})
    who = person(session, sid)
    earlier(session, "sms", who, when=WORK - timedelta(days=1))
    row = message(session, who)
    session.commit()

    assert (await send(row)).code == "accepted"


# ── 5 권한 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("channel", ["sms", "kakao", "call"])
async def test_delegated_agent_send_passes_and_is_recorded_as_delegated(session, sid, fake_channel, channel):
    connect(session, **DELEGATED)
    row = row_for(session, channel, person(session, sid), origin="agent", origin_name="에이전트")
    session.commit()

    out = await send(row, AGENT)

    assert out.code in ("accepted", "queued") and len(fake_channel.delivered) == 1
    row = reread(session, row)
    assert (row.send_mode, row.approved_by) == ("delegated", None)


@pytest.mark.parametrize("channel", ["sms", "kakao", "call"])
@pytest.mark.parametrize("case", sorted(set(CASES) - {"agent_no_delegation"}))
async def test_delegated_agent_send_passes_all_other_checks(session, sid, fake_channel, case, channel):
    """위임이어도 나머지 검사는 그대로 받는다 — 사람이 보낼 때와 같은 코드에서 멈춘다."""
    row, _, now = arrange(session, sid, case, channel)
    conn = outreach.connection(session)
    conn.agent_sms = conn.agent_kakao = conn.agent_call = "delegate"
    session.commit()

    out = await send(row, AGENT, now)

    assert (out.code, out.rule) == expected(case, channel) and fake_channel.delivered == []


async def test_delegation_is_per_channel(session, sid, fake_channel):
    connect(session, agent_sms="delegate")
    who = person(session, sid)
    text_row, call_row = message(session, who, origin="agent"), call(session, who, origin="agent")
    kakao_row = message(session, person(session, sid, OTHER_PHONE), channel="kakao", origin="agent")
    session.commit()

    assert (await send(text_row, AGENT)).code == "accepted"
    assert (await send(call_row, AGENT)).code == "needs_approval"
    assert (await send(kakao_row, AGENT)).code == "needs_approval"  # 카카오톡 줄은 카카오톡 권한도 있어야 한다


async def test_kakao_delegation_alone_does_not_send_an_sms(session, sid, fake_channel):
    """카카오톡만 위임인데 카카오톡이 잠겨 문자로 나갈 줄 — 문자 권한이 「승인 받기」면 나가지 않는다."""
    connect(session, agent_kakao="delegate")
    row = message(session, person(session, sid), channel="kakao", origin="agent")
    session.commit()

    assert (await send(row, AGENT)).code == "needs_approval" and fake_channel.delivered == []


@pytest.mark.parametrize("mode,delegate,code", [
    ("manual", False, "accepted"), ("approved", False, "accepted"), ("delegated", True, "accepted"),
    ("delegated", False, "needs_approval"), (None, True, "needs_approval"), ("anything", True, "needs_approval"),
])
async def test_system_worker_uses_the_rows_send_mode(session, sid, fake_channel, mode, delegate, code):
    """일꾼(system)은 줄에 적힌 send_mode 를 쓴다: 사람이 보냈거나 승인한 것은 그대로, delegated 는 지금도 위임일 때만,
    적힌 것이 없으면(아무도 승인하지 않음) 나가지 않는다."""
    connect(session, **(DELEGATED if delegate else {}))
    row = message(session, person(session, sid), origin="agent", status="scheduled", scheduled_at=WORK,
                  send_mode=mode, approved_by="김공정" if mode == "approved" else None)
    session.commit()

    out = await send(row, SYSTEM)

    assert out.code == code and len(fake_channel.delivered) == (code == "accepted")
    row = reread(session, row)
    if code == "accepted":
        assert (row.send_mode, row.approved_by) == (mode, "김공정" if mode == "approved" else None)
    else:
        assert (out.rule, row.status, row.send_mode) == (5, "draft", None) and "승인" in row.fail_reason


async def test_human_send_of_own_draft_is_manual(session, sid, fake_channel):
    connect(session)
    row = call(session, person(session, sid))
    session.commit()

    assert (await send(row, USER)).code == "queued"
    row = reread(session, row)
    assert (row.send_mode, row.approved_by) == ("manual", None)


# ── 6 중복 ────────────────────────────────────────────────────────────


async def test_double_click_two_rows_same_body_sends_one(session, sid, fake_channel):
    """두 번 눌러 생긴 두 줄(같은 사람·채널·글): 둘째는 duplicate. 120초가 지나면 나가고, 글이 다르면 바로 나간다."""
    connect(session)
    who = person(session, sid)
    first, second, spaced = message(session, who), message(session, who), message(session, who, body=f"  {BODY}\n")
    different, later = message(session, who, body="다른 물음입니다"), message(session, who)
    session.commit()

    assert (await send(first)).code == "accepted"
    for twin in (second, spaced):
        out = await send(twin, USER, WORK + timedelta(seconds=gate.DUPLICATE_WINDOW_S - 1))
        assert (out.code, out.rule) == ("duplicate", 6)
        twin = reread(session, twin)
        assert twin.status == "draft" and twin.fail_reason and twin.claimed_at is None
    assert (await send(different, USER, WORK + timedelta(seconds=5))).code == "accepted"
    assert (await send(later, USER, WORK + timedelta(seconds=gate.DUPLICATE_WINDOW_S + 1))).code == "accepted"
    assert [d.row_id for d in fake_channel.delivered] == [first.id, different.id, later.id]


@pytest.mark.parametrize("status,code", [("sending", "duplicate"), ("accepted", "duplicate"), ("delivered", "duplicate"),
                                         ("unconfirmed", "duplicate"), ("failed", "accepted")])
async def test_same_text_is_blocked_while_the_first_may_have_gone_out(session, sid, fake_channel, status, code):
    """앞 줄이 나가는 중이거나 나갔거나 「보냈는지 확인 필요」면 같은 글의 새 줄을 막는다(확인 필요인 글은 이미 갔을 수 있다).
    가지 않았음이 확실한 것(failed)만 다시 보내기를 막지 않는다."""
    connect(session)
    who = person(session, sid)
    message(session, who, status=status, claimed_at=WORK - timedelta(seconds=30))
    row = message(session, who)
    session.commit()

    out = await send(row)

    assert out.code == code and len(fake_channel.delivered) == (code == "accepted")
    if code == "duplicate":
        assert out.rule == 6 and reread(session, row).status == "draft"


async def test_unconfirmed_text_can_be_resent_after_the_window(session, sid, fake_channel):
    """「보냈는지 확인 필요」인 글도 120초가 지나면 사람이 새 줄로 다시 보낼 수 있다."""
    connect(session)
    who = person(session, sid)
    message(session, who, status="unconfirmed", claimed_at=WORK - timedelta(seconds=gate.DUPLICATE_WINDOW_S + 1))
    row = message(session, who)
    session.commit()

    assert (await send(row)).code == "accepted"


async def test_same_text_to_the_same_number_from_two_projects_is_one_send(session, sid, fake_channel):
    connect(session)
    here, there = person(session, sid), person(session, schedules.store(session, schedules.sample()))
    rows = [message(session, here), message(session, there), message(session, peer_number=PHONE)]
    session.commit()

    assert [(await send(row)).code for row in rows] == ["accepted", "duplicate", "duplicate"]


async def test_scheduled_twins_do_not_both_leave(session, sid, fake_channel):
    """근무 밖에 두 번 눌러 둘 다 예약된 줄 — 때가 되면 하나만 나가고 다른 하나는 초안으로 돌아간다(뒤에 다시 나가지 않는다)."""
    connect(session)
    who = person(session, sid)
    rows = [message(session, who), message(session, who)]
    session.commit()
    assert [(await send(row, USER, OFF)).code for row in rows] == ["scheduled", "scheduled"]

    outs = [await send(row, SYSTEM, MONDAY) for row in rows]
    much_later = await send(rows[1], SYSTEM, MONDAY + timedelta(minutes=10))

    assert [o.code for o in outs] == ["accepted", "duplicate"]
    assert reread(session, rows[1]).status == "draft" and much_later.code == "needs_approval"
    assert len(fake_channel.delivered) == 1


async def test_same_purpose_call_is_not_placed_twice(session, sid, fake_channel):
    connect(session, limits_json={"per_contact_calls_daily": 9})
    who = person(session, sid)
    first, twin = call(session, who, purpose_key="pour-3f"), call(session, who, purpose_key="pour-3f")
    other_purpose = call(session, who, purpose_key="rebar-in")
    session.commit()

    assert (await send(first)).code == "queued"
    first.status = "completed"  # 통화가 끝남 — 진행 중 통화는 아니지만 방금 같은 목적으로 걸었다
    session.commit()

    assert (await send(twin, USER, WORK + timedelta(seconds=60))).code == "duplicate"
    assert (await send(other_purpose, USER, WORK + timedelta(seconds=60))).code == "queued"
    assert [d.row_id for d in fake_channel.delivered] == [first.id, other_purpose.id]


@pytest.mark.parametrize("ended", ["no_answer", "busy", "failed"])
async def test_redial_after_a_call_that_did_not_connect_is_not_a_duplicate(session, sid, fake_channel, ended):
    connect(session)
    who = person(session, sid)
    call(session, who, purpose_key="pour-3f", status=ended, claimed_at=WORK - timedelta(seconds=40))
    redial = call(session, who, purpose_key="pour-3f")
    session.commit()

    assert (await send(redial)).code == "queued"


async def test_live_call_with_the_same_number_blocks_another_call(session, sid, fake_channel):
    """같은 사람(같은 번호)이 다른 프로젝트 통화 중이어도, 주소록에 없는 번호와 통화 중이어도 또 걸지 않는다."""
    connect(session)
    there = person(session, schedules.store(session, schedules.sample()))
    call(session, there, status="in_call", claimed_at=WORK - timedelta(minutes=3))
    rows = [call(session, person(session, sid)), call(session, peer_number=PHONE)]
    other = call(session, person(session, sid, OTHER_PHONE))
    session.commit()

    assert [(await send(row)).code for row in rows] == ["duplicate", "duplicate"]
    assert (await send(other)).code == "queued"


async def test_scheduled_call_with_the_same_purpose_blocks_another(session, sid, fake_channel):
    """같은 연락처에 같은 목적의 예약 통화가 있으면 또 걸지 않는다. 목적 손잡이가 빈 통화끼리는 견주지 않는다."""
    connect(session)
    who = person(session, sid)
    call(session, who, purpose_key="pour-3f", status="scheduled", scheduled_at=MONDAY, send_mode="manual")
    call(session, who, purpose_key="", status="scheduled", scheduled_at=MONDAY, send_mode="manual")
    same, unkeyed = call(session, who, purpose_key="pour-3f"), call(session, who, purpose_key="")
    session.commit()

    out = await send(same)
    assert (out.code, out.rule) == ("duplicate", 6)
    assert (await send(unkeyed)).code == "queued"


# ── 7 채널 고르기 ──────────────────────────────────────────────────────


def _template(session, conn, **over) -> KakaoTemplate:
    values = {"connection_id": conn.id, "channel": "@chronos", "provider_template_id": "tpl-1", "use": "체크인 요청",
              "body": "#{이름}님, #{날짜} 타설 예정입니다. 가능 여부를 알려 주세요.", "status": "reviewing", **over}
    row = KakaoTemplate(**values)
    session.add(row)
    session.flush()
    return row


async def test_kakao_without_approved_template_goes_as_sms(session, sid, fake_channel):
    """카카오톡 문안이 승인 전 → 문자로: 줄의 채널이 sms 가 되고 글은 채운 문안, 판정 앞에 kakao_not_ready."""
    conn = connect(session)
    template = _template(session, conn)
    row = message(session, person(session, sid), channel="kakao", body="", template_id=template.id,
                  template_vars_json={"이름": "박현장", "날짜": "11월 30일"})
    session.commit()

    out = await send(row)

    row = reread(session, row)
    assert out.code == "accepted"
    assert fake_channel.delivered[0].channel == "sms" and row.channel == "sms"
    assert row.body == "박현장님, 11월 30일 타설 예정입니다. 가능 여부를 알려 주세요."
    assert trail(session, row) == [("kakao_not_ready", "noted"), ("channel_choice", "allowed"), ("delivery", "allowed")]
    assert events.of(session, Ref("message", row.id))[1]["detail"] == "sms"
    assert outreach.sent_count(session, "sms", WORK.date()) == 1  # 문자로 나갔으니 문자로 센다


async def test_kakao_fallback_prefers_the_sms_text_tied_to_the_template(session, sid, fake_channel):
    conn = connect(session)
    template = _template(session, conn, fallback_body="[문자] #{이름}님 #{날짜} 타설 확인 부탁드립니다.")
    row = message(session, person(session, sid), channel="kakao", body="화면에 보인 글", template_id=template.id,
                  template_vars_json={"이름": "박현장", "날짜": "11월 30일"})
    session.commit()

    assert (await send(row)).code == "accepted"
    assert reread(session, row).body == "[문자] 박현장님 11월 30일 타설 확인 부탁드립니다."


@pytest.mark.parametrize("body,code", [(BODY, "accepted"), ("", "not_sendable")])
async def test_kakao_template_with_a_missing_variable_is_never_sent_half_filled(session, sid, fake_channel, body, code):
    """변수를 다 채우지 못한 문안은 보내지 않는다 — 줄에 적힌 글이 있으면 그것으로, 없으면 보낼 글 없음."""
    conn = connect(session)
    template = _template(session, conn)
    row = message(session, person(session, sid), channel="kakao", body=body, template_id=template.id,
                  template_vars_json={"이름": "박현장"})
    session.commit()

    out = await send(row)

    assert out.code == code and len(fake_channel.delivered) == (code == "accepted")
    if code == "accepted":
        assert reread(session, row).body == BODY


async def test_kakao_row_without_a_template_goes_as_sms_with_its_own_text(session, sid, fake_channel):
    connect(session)
    row = message(session, person(session, sid), channel="kakao")
    session.commit()

    assert (await send(row)).code == "accepted"
    row = reread(session, row)
    assert (row.channel, row.body) == ("sms", BODY) and fake_channel.delivered[0].channel == "sms"


async def test_kakao_goes_as_sms_while_no_kakao_channel_is_registered(session, sid, no_real_channels):
    """문안이 승인돼 있어도 카카오톡 통로가 등록돼 있지 않으면(지금은 늘) 문자로 나간다."""
    conn = connect(session)
    template = _template(session, conn, status="approved")
    row = message(session, person(session, sid), channel="kakao", template_id=template.id,
                  template_vars_json={"이름": "박현장", "날짜": "11월 30일"})
    session.commit()
    fake = FakeChannel()

    with registry.pinned({"sms": fake.lane("sms"), "call": fake.lane("call")}):
        out = await send(row)

    assert out.code == "accepted" and [d.channel for d in fake.delivered] == ["sms"]
    assert trail(session, row)[0] == ("kakao_not_ready", "noted")


async def test_ready_kakao_goes_through_the_kakao_channel(session, sid, fake_channel):
    """통로가 있고 문안이 승인됐을 때만 카카오톡으로(가짜로만 시험 — 실제 통로는 등록하지 않는다)."""
    conn = connect(session)
    template = _template(session, conn, status="approved")
    foreign = _template(session, connect(session, is_default=False), status="approved")
    who = person(session, sid)
    row = message(session, who, channel="kakao", template_id=template.id)
    other = message(session, who, channel="kakao", body="다른 연결의 문안", template_id=foreign.id)
    session.commit()

    assert (await send(row)).code == "accepted"
    assert (await send(other)).code == "accepted"

    assert [d.channel for d in fake_channel.delivered] == ["kakao", "sms"]  # 다른 연결의 문안은 쓰지 않는다
    row = reread(session, row)
    assert row.channel == "kakao" and trail(session, row) == [("channel_choice", "allowed"), ("delivery", "allowed")]
    assert events.of(session, Ref("message", row.id))[0]["detail"] == "kakao"
