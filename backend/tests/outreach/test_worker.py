"""연락 일꾼(Task 71) — 때가 된 예약 보내기(문을 거쳐) · 상태 조회 · 들어온 문자 받기.

시험은 일꾼을 띄우지 않고 `worker.tick(now=…)` 을 정해 둔 시각으로 한 바퀴씩 돌린다(conftest 의 quiet_outreach_worker).
제공사는 가짜(fake_provider), 통로는 가짜(fake_channel)이거나 밝힌 시험에서만 진짜다. 번호·키는 가상이다.
"""

import asyncio
import contextlib
import logging
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.main import app
from app.outreach import phone, provider, worker
from app.outreach.channels import sms
from app.outreach.harness import door, events, gate
from app.outreach.harness.types import Delivered, Ref
from app.outreach.provider import Delivery, Inbound, ProviderFailed, Received
from app.outreach.text import inbox
from app.store import outreach
from app.store.tables_outreach import NotifyConnection, OutreachMessage
from app.store.timeutil import as_utc
from tests import schedules
from tests.harness_doubles import Delivery as Handed
from tests.outreach.harness.test_gate import (
    BODY,
    OFF,
    OTHER_PHONE,
    PHONE,
    WORK,
    connect,
    db_path,
    message,
    person,
    reread,
    trail,
)
from tests.outreach_doubles import SENTINEL_KEY, SENTINEL_PHONE, assert_clean

pytestmark = pytest.mark.usefixtures("time_guard")

NOW = WORK  # 금요일 10시(서울) — 근무 중
OUR = "07000000000"  # connect() 의 발신번호
STRANGER = "01000000177"


class Runaway(BaseException):
    """시험의 가짜가 정해 둔 횟수보다 많이 불렸다(끝없이 도는 고리를 가짜가 스스로 끊는다)."""


# ── 도우미 ────────────────────────────────────────────────────────────


def due(session, to, **over) -> OutreachMessage:
    """사람이 예약해 둔, 때가 된 줄 하나."""
    return message(session, to, **{"status": "scheduled", "send_mode": "manual", "scheduled_at": NOW - timedelta(minutes=1),
                                   **over})


def sent(session, to, pid: str | None = "FAKE-A", **over) -> OutreachMessage:
    """제공사가 받은 줄(accepted) 하나 — 15초 전에 나갔다."""
    at = NOW - timedelta(seconds=15)
    return message(session, to, **{"status": "accepted", "provider_message_id": pid, "claimed_at": at, "sent_at": at,
                                   "send_mode": "manual", **over})


def text_in(sender: str = PHONE, body: str = "내일 가능합니다", *, pid: str = "MGIN0001", at: datetime | None = None,
            to: str = OUR, **over) -> Inbound:
    return Inbound(provider_id=pid, from_number=sender, body=body, at=as_utc(at or NOW - timedelta(minutes=1)),
                   has_media=False, to_number=to, **over)


def receive(fake, *items: Inbound, fetched_at: datetime = NOW, **flags) -> list:
    """가짜의 received 를 정해 둔 답 하나로 바꾼다(since 와 상관없이 같은 줄 — 겹쳐 오는 것을 흉내 낸다). 물은 since 목록."""
    asked: list = []

    async def received(since):
        fake._called("received")
        if len(asked) >= 50:
            raise Runaway("received 가 50번 넘게 불렸습니다")
        asked.append(since)
        return Received(items=list(items), fetched_at=as_utc(fetched_at), **flags)

    fake.received = received
    return asked


def inbound_rows(session) -> list[OutreachMessage]:
    session.expire_all()
    return list(session.scalars(select(OutreachMessage).where(OutreachMessage.direction == "in").order_by(OutreachMessage.id)))


def out_rows(session, kind: str) -> list[OutreachMessage]:
    session.expire_all()
    return list(session.scalars(select(OutreachMessage).where(OutreachMessage.direction == "out",
                                                              OutreachMessage.kind == kind).order_by(OutreachMessage.id)))


def details(session, row) -> list[tuple[str, str, str]]:
    session.expire_all()
    return [(e["rule"], e["verdict"], e["detail"]) for e in events.of(session, Ref("message", row.id))]


def cursor(session) -> datetime | None:
    session.expire_all()
    return session.scalar(select(NotifyConnection.reply_cursor))


@pytest.fixture
def handed(monkeypatch) -> list[int]:
    """inbox.enqueue 로 넘어간 메시지 id."""
    got: list[int] = []
    monkeypatch.setattr(inbox, "enqueue", got.append)
    return got


# ── ① 때가 된 예약 ────────────────────────────────────────────────────


async def test_due_row_goes_out_through_the_gate_as_the_system(session, sid, fake_channel, fake_provider, monkeypatch):
    connect(session)
    who = person(session, sid)
    row, later = due(session, who), due(session, who, body="다음 주 글", scheduled_at=NOW + timedelta(minutes=5))
    session.commit()
    seen = []
    real = gate.dispatch

    async def spy(kind, row_id, actor, *, now=None):
        seen.append((kind, row_id, actor.kind))
        return await real(kind, row_id, actor, now=now)

    monkeypatch.setattr(gate, "dispatch", spy)

    first = await worker.tick(now=NOW)
    await worker.tick(now=NOW + timedelta(seconds=20))

    assert seen == [("message", row.id, "system")] and first["due"] == 1
    assert fake_channel.delivered == [Handed("sms", row.id)]  # 한 번만 — 두 번째 바퀴는 다시 넣지 않는다
    assert reread(session, row).status == "accepted" and reread(session, later).status == "scheduled"


async def test_due_row_is_rechecked_from_the_top(session, sid, fake_channel, fake_provider):
    """예약 뒤 위임을 껐다 → 때가 되면 처음부터 다시 검사받아 초안으로 돌아가고 까닭이 남는다. 보낸 것 없음."""
    conn = connect(session, agent_sms="delegate")
    who = person(session, sid)
    row = due(session, who, origin="agent", origin_name="에이전트", send_mode="delegated")
    session.commit()
    conn.agent_sms = "approve"
    session.commit()

    await worker.tick(now=NOW)

    row = reread(session, row)
    assert row.status == "draft" and "승인" in row.fail_reason and row.send_mode is None
    assert fake_channel.delivered == [] and fake_provider.sent == []
    assert trail(session, row) == [("permission", "blocked")]


async def test_due_row_after_dnc_is_not_sent(session, sid, fake_channel, fake_provider):
    connect(session)
    who = person(session, sid)
    row = due(session, who)
    outreach.mark_do_not_contact(session, PHONE, reason="전화로 요청")
    session.commit()

    await worker.tick(now=NOW)

    row = reread(session, row)
    assert row.status == "draft" and row.fail_reason == "수신 거부한 번호입니다" and fake_channel.delivered == []


async def test_due_row_under_test_mode_is_blocked_not_sent(session, sid, fake_channel, fake_provider):
    conn = connect(session)
    row = due(session, person(session, sid))
    session.commit()
    conn.test_mode = True  # 예약 뒤 시험 모드가 켜짐
    session.commit()

    await worker.tick(now=NOW)

    assert reread(session, row).status == "blocked_test" and fake_channel.delivered == []


async def test_worker_never_resends_failed_or_unconfirmed_rows(session, sid, fake_channel, fake_provider):
    connect(session)
    who = person(session, sid)
    old = NOW - timedelta(hours=1)
    rows = [message(session, who, status=status, scheduled_at=old, claimed_at=old, send_mode="manual", body=f"글 {status}")
            for status in ("failed", "unconfirmed", "draft", "blocked_test", "sending")]
    session.commit()

    await worker.tick(now=NOW)

    assert fake_channel.delivered == [] and fake_provider.sent == []
    assert [reread(session, row).status for row in rows[:4]] == ["failed", "unconfirmed", "draft", "blocked_test"]
    assert [trail(session, row) for row in rows[:4]] == [[]] * 4  # 문에 넣지도 않았다
    assert reread(session, rows[4]).status == "unconfirmed" and trail(session, rows[4]) == [("delivery", "noted")]


async def test_draft_with_a_past_time_is_never_picked_up(session, sid, fake_channel, fake_provider):
    """때가 된 줄은 상태(scheduled)로 고른다 — 시각만 지난 초안(「승인 받기」에서 도구가 만든 회신 초안은 scheduled_at 을
    달고 있다)은 사람이 승인하기 전에는 나가지 않는다."""
    connect(session, agent_sms="delegate")
    who = person(session, sid)
    callback = message(session, who, origin="agent", origin_name="AI 비서", status="draft",
                       scheduled_at=NOW - timedelta(hours=2))
    session.commit()

    for step in range(2):
        result = await worker.tick(now=NOW + timedelta(seconds=20 * step))
        assert result["due"] == 0

    callback = reread(session, callback)
    assert (callback.status, callback.fail_reason, callback.claimed_at) == ("draft", None, None)
    assert trail(session, callback) == [] and fake_channel.delivered == [] and fake_provider.sent == []


async def test_cancel_racing_the_worker_ends_as_a_cancelled_draft(session, sid, fake_channel, fake_provider, monkeypatch):
    """일꾼은 줄을 미리 차지하지 않는다(차지는 문의 조건부 쓰기 하나뿐) — 일꾼이 줄을 고른 뒤 사람이 예약을 취소하면
    (scheduled → draft, send_mode·scheduled_at 비움) 그 줄은 취소된 초안으로 남고 나가지 않는다."""
    connect(session)
    row = due(session, person(session, sid))
    session.commit()
    real = gate.dispatch

    async def cancelled_first(kind, row_id, actor, *, now=None):
        session.execute(update(OutreachMessage).where(OutreachMessage.id == row_id, OutreachMessage.status == "scheduled")
                        .values(status="draft", send_mode=None, approved_by=None, scheduled_at=None))
        session.commit()
        return await real(kind, row_id, actor, now=now)

    monkeypatch.setattr(gate, "dispatch", cancelled_first)

    await worker.tick(now=NOW)
    monkeypatch.setattr(gate, "dispatch", real)
    await worker.tick(now=NOW + timedelta(seconds=20))

    row = reread(session, row)
    assert (row.status, row.send_mode, row.scheduled_at, row.claimed_at) == ("draft", None, None, None)
    assert fake_channel.delivered == [] and fake_provider.sent == []


@pytest.mark.real_channel("sms")
async def test_due_row_is_sent_once_by_the_real_channel(session, sid, fake_provider):
    connect(session)
    row = due(session, person(session, sid))
    session.commit()

    for step in range(3):
        await worker.tick(now=NOW + timedelta(seconds=20 * step))

    row = reread(session, row)
    assert len(fake_provider.sent) == 1 and fake_provider.sent[0].idempotency_key == row.idempotency_key
    assert (row.status, row.provider_message_id) == ("accepted", "FAKE0001")


async def test_off_hours_due_row_is_scheduled_again_not_sent(session, sid, fake_channel, fake_provider):
    connect(session)
    row = due(session, person(session, sid), scheduled_at=OFF - timedelta(minutes=1))
    session.commit()

    await worker.tick(now=OFF)  # 금요일 19시

    row = reread(session, row)
    assert row.status == "scheduled" and as_utc(row.scheduled_at) > as_utc(OFF) and fake_channel.delivered == []


# ── 서버가 다시 떴을 때·오래 남은 sending ─────────────────────────────


async def test_restart_never_resends_a_sending_row(session, sid, fake_channel, fake_provider):
    connect(session)
    who = person(session, sid)
    row = message(session, who, status="sending", claimed_at=NOW - timedelta(minutes=6), send_mode="manual",
                  scheduled_at=NOW - timedelta(minutes=7))
    session.commit()

    assert worker.recover(now=NOW) == 1
    assert worker.recover(now=NOW) == 0
    await worker.tick(now=NOW)

    row = reread(session, row)
    assert (row.status, row.fail_reason) == ("unconfirmed", gate.UNSURE)
    assert details(session, row) == [("server_restart", "noted", worker.RESTARTED)]
    assert fake_channel.delivered == [] and fake_provider.sent == []


def test_recover_leaves_rows_claimed_after_the_server_started(session, sid):
    """일꾼의 첫 걸음이 돌기 전에 들어온 보내기(지금 나가는 중)는 건드리지 않는다."""
    connect(session)
    who = person(session, sid)
    before = message(session, who, status="sending", claimed_at=NOW - timedelta(seconds=worker.STALE_SENDING_S + 1))
    in_flight = message(session, who, status="sending", claimed_at=NOW + timedelta(seconds=1), body="방금 누른 글")
    session.commit()

    assert worker.recover(now=NOW + timedelta(minutes=10), before=NOW) == 1  # in_flight 도 300초를 넘겼지만 뜬 뒤에 차지됐다

    assert reread(session, before).status == "unconfirmed" and reread(session, in_flight).status == "sending"


def test_recover_leaves_young_sending_rows_to_whoever_is_sending_them(session, sid):
    """둘째 프로세스가 같은 DB 로 떠도 첫 프로세스가 지금 보내는 줄을 「확인 필요」로 옮기지 않는다 — 뜨기 전에 차지된 줄이라도
    STALE_SENDING_S(바퀴의 정리와 같은 문턱)보다 젊으면 그대로 둔다(정말 남은 줄이면 바퀴의 정리가 뒤에 옮긴다)."""
    connect(session)
    who = person(session, sid)
    young = message(session, who, status="sending", claimed_at=NOW - timedelta(seconds=worker.STALE_SENDING_S - 5))
    old = message(session, who, status="sending", claimed_at=NOW - timedelta(seconds=worker.STALE_SENDING_S + 5),
                  body="오래 남은 글")
    session.commit()

    assert worker.recover(now=NOW, before=NOW) == 1

    assert reread(session, young).status == "sending" and details(session, young) == []
    assert reread(session, old).status == "unconfirmed"


async def test_stale_sending_row_becomes_unconfirmed_on_a_later_tick(session, sid, fake_channel, fake_provider):
    """문이 결과를 끝내 적지 못한 줄은 sending 으로 남아 같은 글을 막는다 — 일꾼이 주기적으로 「확인 필요」로 옮긴다."""
    connect(session)
    who = person(session, sid)
    stale = message(session, who, status="sending", claimed_at=NOW - timedelta(seconds=worker.STALE_SENDING_S + 1))
    fresh = message(session, who, status="sending", claimed_at=NOW - timedelta(seconds=30), body="나가는 중인 글")
    session.commit()

    await worker.tick(now=NOW)

    stale = reread(session, stale)
    assert (stale.status, stale.fail_reason) == ("unconfirmed", gate.UNSURE) and reread(session, fresh).status == "sending"
    assert details(session, stale) == [("delivery", "noted", worker.RESULT_LOST)]
    assert fake_channel.delivered == [] and fake_provider.sent == []


# ── ② 상태 조회 ───────────────────────────────────────────────────────


async def test_status_poll_marks_delivered_and_backs_off(session, sid, fake_provider):
    connect(session)
    row = sent(session, person(session, sid))
    session.commit()

    def polls() -> int:
        return fake_provider.log.count("message_status")

    await worker.tick(now=NOW)  # 나간 지 15초 — 첫 조회(10초 뒤부터)
    row = reread(session, row)
    assert polls() == 1 and (row.status, row.checks) == ("accepted", 1) and as_utc(row.last_checked_at) == as_utc(NOW)

    await worker.tick(now=NOW + timedelta(seconds=10))  # 다음 조회는 20초 뒤
    assert polls() == 1
    await worker.tick(now=NOW + timedelta(seconds=20))
    assert polls() == 2 and reread(session, row).checks == 2
    await worker.tick(now=NOW + timedelta(seconds=50))  # 그다음은 40초 뒤(20 + 40 = 60초)
    assert polls() == 2

    fake_provider.statuses["FAKE-A"] = Delivery(state="delivered")
    await worker.tick(now=NOW + timedelta(seconds=60))
    row = reread(session, row)
    assert polls() == 3 and row.status == "delivered" and as_utc(row.delivered_at) == as_utc(NOW + timedelta(seconds=60))
    assert details(session, row) == [("delivery_update", "allowed", "delivered")]

    await worker.tick(now=NOW + timedelta(hours=1))  # 끝난 줄은 다시 묻지 않는다
    assert polls() == 3 and fake_provider.sent == []


def test_status_poll_gaps_double_up_to_five_minutes():
    assert [worker.status_gap(checks) for checks in range(8)] == [10, 20, 40, 80, 160, 300, 300, 300]


async def test_status_poll_marks_failed_with_our_own_text(session, sid, fake_provider):
    connect(session)
    row = sent(session, person(session, sid))
    session.commit()
    fake_provider.statuses["FAKE-A"] = Delivery(state="failed", fail_code="handset_off", fail_text=f"제공사 글 {SENTINEL_PHONE}")

    await worker.tick(now=NOW)

    row = reread(session, row)
    assert (row.status, row.fail_reason) == ("failed", "단말기 전원이 꺼져 있습니다.")  # code 를 우리 표의 글로 — 받은 글은 버린다
    assert details(session, row) == [("delivery_update", "blocked", "failed")]


async def test_unknown_failure_code_gets_the_generic_sentence(session, sid, fake_provider):
    connect(session)
    row = sent(session, person(session, sid))
    session.commit()
    fake_provider.statuses["FAKE-A"] = Delivery(state="failed", fail_code="brand_new_code", fail_text=None)

    await worker.tick(now=NOW)

    assert reread(session, row).fail_reason == worker.DELIVERY_FAILED


async def test_status_answer_does_not_overwrite_a_row_settled_meanwhile(session, sid, fake_provider):
    """제공사에 묻는 사이 사람이 그 줄을 정리했으면(더는 기다리는 줄이 아니면) 답을 덮어쓰지 않는다."""
    connect(session)
    row = sent(session, person(session, sid), status="unconfirmed", fail_reason=gate.UNSURE)
    session.commit()

    async def status(provider_id):
        fake_provider._called("message_status")
        row.status, row.fail_reason = "failed", "사람이 실패로 정리함"
        session.commit()
        return Delivery(state="delivered")

    fake_provider.message_status = status

    await worker.tick(now=NOW)

    row = reread(session, row)
    assert (row.status, row.fail_reason, row.checks, details(session, row)) == ("failed", "사람이 실패로 정리함", 0, [])


def test_closing_a_row_that_is_no_longer_sending_changes_nothing(session, sid):
    connect(session)
    row = sent(session, person(session, sid))  # 그 사이 문이 결과(accepted)를 적었다
    session.commit()

    assert worker._close(session, [row.id], "delivery", worker.RESULT_LOST, as_utc(NOW)) == 0

    assert reread(session, row).status == "accepted" and details(session, row) == []


async def test_unconfirmed_is_resolved_by_status_poll_not_resend(session, sid, fake_provider, fake_channel):
    """제공사 id 가 있는 「확인 필요」 줄은 같은 조회로 풀린다. id 가 없는 줄은 사람이 정할 때까지 그대로 — 어느 쪽도 다시 보내지 않는다."""
    connect(session)
    who = person(session, sid)
    known = sent(session, who, status="unconfirmed", fail_reason=gate.UNSURE)
    blind = sent(session, who, pid=None, status="unconfirmed", fail_reason=gate.UNSURE, body="id 없는 글")
    session.commit()
    fake_provider.statuses["FAKE-A"] = Delivery(state="delivered")

    await worker.tick(now=NOW)
    await worker.tick(now=NOW + timedelta(minutes=10))

    known, blind = reread(session, known), reread(session, blind)
    assert (known.status, known.fail_reason) == ("delivered", None)
    assert (blind.status, blind.fail_reason, blind.checks) == ("unconfirmed", gate.UNSURE, 0)
    assert fake_provider.sent == [] and fake_channel.delivered == [] and fake_provider.log.count("message_status") == 1


async def test_status_gives_up_after_72_hours(session, sid, fake_provider):
    connect(session)
    who = person(session, sid)
    long_ago = NOW - timedelta(hours=72, minutes=1)
    old = sent(session, who, claimed_at=long_ago, sent_at=long_ago)
    recent = sent(session, who, pid="FAKE-B", claimed_at=NOW - timedelta(hours=71), sent_at=NOW - timedelta(hours=71),
                  body="어제 글")
    session.commit()

    await worker.tick(now=NOW)
    await worker.tick(now=NOW + timedelta(minutes=30))

    old = reread(session, old)
    assert (old.status, old.fail_reason, old.checks) == ("accepted", worker.GAVE_UP, 0)
    assert details(session, old) == [("delivery_update", "noted", "gave_up")]  # 한 번만
    assert reread(session, recent).checks >= 1  # 72시간 안의 줄은 계속 묻는다


async def test_row_past_72_hours_is_not_asked_even_before_it_is_closed(session, sid, fake_provider, monkeypatch):
    """그만 묻기 표시는 한 바퀴에 SWEEP_ROWS 줄씩 한다 — 아직 표시되지 않은 72시간 넘은 줄도 조회에는 들지 않는다."""
    connect(session)
    long_ago = NOW - timedelta(hours=80)
    old = sent(session, person(session, sid), claimed_at=long_ago, sent_at=long_ago)
    session.commit()
    monkeypatch.setattr(worker, "SWEEP_ROWS", 0)

    await worker.tick(now=NOW)

    assert fake_provider.log.count("message_status") == 0 and reread(session, old).checks == 0


async def test_fallback_is_marked(session, sid, fake_provider):
    connect(session)
    row = sent(session, person(session, sid), channel="kakao")
    session.commit()
    fake_provider.statuses["FAKE-A"] = Delivery(state="delivered", fell_back=True)

    await worker.tick(now=NOW)

    row = reread(session, row)
    assert row.fallback_sms is True and row.status == "delivered"


async def test_one_messages_lookup_failure_only_delays_that_message(session, sid, fake_provider):
    """제공사가 그 메시지만 모른다(404)면 그 줄의 다음 조회만 미룬다 — 다른 줄과 들어온 문자 조회는 그대로."""
    connect(session)
    who = person(session, sid)
    lost, fine = sent(session, who), sent(session, who, pid="FAKE-B", body="다른 글")
    session.commit()
    real = fake_provider.message_status

    async def status(provider_id):
        if provider_id == "FAKE-A":
            fake_provider._called("message_status")
            raise ProviderFailed("bad_request", "그 메시지를 찾을 수 없습니다.", 404)
        return await real(provider_id)

    fake_provider.message_status = status
    fake_provider.statuses["FAKE-B"] = Delivery(state="delivered")

    await worker.tick(now=NOW)

    assert (reread(session, lost).status, reread(session, lost).checks) == ("accepted", 1)
    assert reread(session, fine).status == "delivered" and "received" in fake_provider.log
    assert worker.status()["quiet_until"] is None


# ── ③ 들어온 문자 ─────────────────────────────────────────────────────


async def test_next_since_is_fetched_at_minus_margin_not_max_at(session, sid, fake_provider):
    connect(session, inbound_mode="known")
    person(session, sid)
    session.commit()
    fetched = NOW + timedelta(seconds=3)
    asked = receive(fake_provider, text_in(at=NOW - timedelta(hours=2)), fetched_at=fetched)

    await worker.tick(now=NOW)
    await worker.tick(now=NOW + timedelta(seconds=20))

    margin = timedelta(seconds=provider.SINCE_MARGIN_S)
    assert as_utc(cursor(session)) == as_utc(fetched) - margin  # 가장 늦은 문자의 시각(두 시간 전)이 아니다
    assert [as_utc(since) for since in asked] == [as_utc(NOW) - margin, as_utc(fetched) - margin]  # 처음엔 지금부터


async def test_text_to_another_sender_number_is_ignored(session, sid, fake_provider, handed):
    connect(session, inbound_mode="known")
    person(session, sid)
    session.commit()
    receive(fake_provider, text_in(pid="MGIN0001", to="07000000456"), text_in(pid="MGIN0002", to=phone.NO_NUMBER),
            text_in(pid="MGIN0003"))

    await worker.tick(now=NOW)

    assert [row.provider_message_id for row in inbound_rows(session)] == ["MGIN0003"] and len(handed) == 1
    assert worker.status()["inbound_other_sender"] == 2


async def test_truncated_fetch_is_surfaced_and_does_not_stall_the_cursor(session, sid, fake_provider):
    """쪽 상한 뒤에 남은 줄은 다시 읽어도 오지 않는다(같은 최신 줄만 온다) — 알리고, 커서는 그대로 나아간다."""
    connect(session, inbound_mode="known")
    person(session, sid)
    session.commit()
    receive(fake_provider, text_in(), truncated=True, skipped=2, redated=1)
    assert worker.status()["inbound_truncated"] == 0

    await worker.tick(now=NOW)
    await worker.tick(now=NOW + timedelta(seconds=20))

    state = worker.status()
    assert state["inbound_truncated"] == 2 and state["inbound_truncated_at"] == as_utc(NOW + timedelta(seconds=20)).isoformat()
    assert state["inbound_skipped"] == 2 and state["inbound_redated"] == 1  # 이 둘은 마지막 조회 한 번의 수
    assert as_utc(cursor(session)) == as_utc(NOW) - timedelta(seconds=provider.SINCE_MARGIN_S)
    assert len(inbound_rows(session)) == 1


async def test_reply_goes_to_the_project_that_messaged_last(session, sid, fake_provider):
    """같은 번호가 두 프로젝트에 있으면 그 번호로 가장 최근에 보낸 프로젝트의 대화에만 들어간다."""
    connect(session, inbound_mode="known")
    other_sid = schedules.store(session, schedules.sample())
    here, there = person(session, sid), person(session, other_sid, name="박현장(다른 현장)")
    sent(session, here, claimed_at=NOW - timedelta(days=1), sent_at=NOW - timedelta(days=1))
    sent(session, there, pid="FAKE-B", claimed_at=NOW - timedelta(days=2), sent_at=NOW - timedelta(days=2))
    message(session, there, body="보내지 않은 초안")  # 초안은 「보낸 것」이 아니다
    message(session, there, status="failed", claimed_at=NOW - timedelta(hours=1), body="실패한 글")  # 가지 않은 것도
    session.commit()
    assert worker.route(session, SENTINEL_PHONE) == (sid, here.id)
    receive(fake_provider, text_in())

    await worker.tick(now=NOW)

    [row] = inbound_rows(session)
    assert (row.schedule_id, row.contact_id) == (sid, here.id)

    sent(session, there, pid="FAKE-C", claimed_at=NOW, sent_at=NOW, body="방금 보낸 글")
    session.commit()
    assert worker.route(session, PHONE) == (other_sid, there.id)


def test_route_without_any_sent_message(session, sid):
    """보낸 것이 없으면 연락처가 한 곳일 때만 그곳. 두 곳이면 정하지 않는다(모르는 번호 묶음으로)."""
    assert worker.route(session, PHONE) is None and worker.route(session, phone.NO_NUMBER) is None
    only = person(session, sid)
    hidden = person(session, sid, name="숨긴 사람", hidden=True)
    session.flush()
    assert worker.route(session, PHONE) == (sid, only.id)
    hidden.hidden = False
    session.flush()
    assert worker.route(session, PHONE) is None
    assert worker.route(session, "+12025550100") is None


async def test_reply_is_linked_to_our_request(session, sid, fake_provider):
    connect(session, inbound_mode="known")
    who = person(session, sid)
    sent(session, who, pid="FAKE-OLD", claimed_at=NOW - timedelta(hours=80), sent_at=NOW - timedelta(hours=80), body="지난주",
         activity_id="A", field_item_id=1, batch_id=3)
    checkin = sent(session, who, claimed_at=NOW - timedelta(hours=5), sent_at=NOW - timedelta(hours=5), activity_id="B",
                   field_item_id=7, batch_id=9)
    session.commit()
    receive(fake_provider, text_in())

    await worker.tick(now=NOW)

    [row] = inbound_rows(session)
    assert row.reply_to_id == checkin.id and row.field_item_id == checkin.field_item_id == 7
    assert (row.activity_id, row.batch_id) == ("B", 9)


async def test_reply_after_72_hours_is_not_linked(session, sid, fake_provider):
    connect(session, inbound_mode="known")
    who = person(session, sid)
    sent(session, who, claimed_at=NOW - timedelta(hours=80), sent_at=NOW - timedelta(hours=80), field_item_id=7)
    session.commit()
    receive(fake_provider, text_in())

    await worker.tick(now=NOW)

    [row] = inbound_rows(session)
    assert (row.contact_id, row.reply_to_id, row.field_item_id) == (who.id, None, None)


async def test_inbound_row_is_written_in_the_stored_form(session, sid, fake_provider):
    connect(session, inbound_mode="known")
    who = person(session, sid)
    session.commit()
    at = NOW - timedelta(minutes=3)
    receive(fake_provider, text_in(body="내일 3층 가능합니다", at=at))

    await worker.tick(now=NOW)

    [row] = inbound_rows(session)
    assert (row.direction, row.channel, row.status, row.origin, row.kind) == ("in", "sms", "received", "peer", "normal")
    assert (row.schedule_id, row.contact_id, row.peer_number, row.caller_class) == (sid, who.id, PHONE, "contact")
    assert (row.body, row.has_media, row.provider_message_id) == ("내일 3층 가능합니다", False, "MGIN0001")
    assert as_utc(row.sent_at) == as_utc(at) and as_utc(row.created_at) == as_utc(NOW)
    assert details(session, row) == [("admission", "allowed", "known_caller")]


async def test_this_text_is_not_counted_against_itself(session, sid, fake_provider, handed):
    """받기 판정에는 방금 쓴 줄의 id 를 넘긴다 — 잦은 문자 상한이 이번 문자까지 세어 한 번 일찍 닫히지 않는다."""
    connect(session, inbound_mode="known", limits_json={"inbound_burst_count": 2})
    person(session, sid)
    session.commit()
    receive(fake_provider, *[text_in(pid=f"MGIN000{i}", body=f"답 {i}") for i in range(1, 4)])

    await worker.tick(now=NOW)

    reasons = [details(session, row)[0][2] for row in inbound_rows(session)]
    assert reasons == ["known_caller", "known_caller", "burst_limit"] and len(handed) == 2


async def test_text_dated_ahead_of_us_is_stored_as_sent_now(session, sid, fake_provider):
    """제공사 시계가 조금 앞서 있어도 「보낸 때」가 앞날이 되지 않는다(답 유예 셈이 어긋나지 않게)."""
    connect(session, inbound_mode="known")
    person(session, sid)
    session.commit()
    receive(fake_provider, text_in(at=NOW + timedelta(minutes=2)))

    await worker.tick(now=NOW)

    [row] = inbound_rows(session)
    assert as_utc(row.sent_at) == as_utc(NOW)


async def test_unknown_sender_is_stored_without_project(session, sid, fake_provider, handed):
    connect(session, inbound_mode="all")
    session.commit()
    receive(fake_provider, text_in(sender="01000000199"))

    await worker.tick(now=NOW)

    [row] = inbound_rows(session)
    assert row.schedule_id is None and row.peer_number == "01000000199"
    assert (row.contact_id, row.caller_class) == (None, "unknown")
    assert details(session, row) == [("admission", "allowed", "unknown_accepted")] and handed == [row.id]  # 고정 안내
    assert [found.id for found in outreach.unknown_messages(session, limit=5)] == [row.id]


async def test_same_inbound_is_stored_once(session, sid, fake_provider, handed):
    connect(session, inbound_mode="known")
    person(session, sid)
    session.commit()
    receive(fake_provider, text_in(), text_in(body="한 번 더 온 같은 줄"))  # 같은 제공사 id 가 한 번에도, 다음 바퀴에도 다시 온다

    for step in range(3):
        await worker.tick(now=NOW + timedelta(seconds=20 * step))

    assert len(inbound_rows(session)) == 1 and len(handed) == 1


def _side_by_side(monkeypatch, module, name: str, job) -> list:
    """두 스레드가 job 을 함께 돌린다. module.name 을 「두 쪽이 다 올 때까지(길어야 1초) 기다린 뒤 진짜를 부름」으로 바꿔 두
    쪽이 확인을 지나 쓰기 바로 앞에서 만나게 한다 — 확인과 쓰기가 한 쓰기 트랜잭션이면 둘째는 확인 앞에서 기다리고, 첫째는
    1초 뒤 혼자 지나간다. 돌려주는 것: 두 job 의 결과."""
    real, meet = getattr(module, name), threading.Barrier(2)

    def waiting(*args, **kwargs):
        with contextlib.suppress(threading.BrokenBarrierError):
            meet.wait(timeout=1.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, waiting)
    results: list = [None, None]

    def run(slot: int) -> None:
        results[slot] = job()

    threads = [threading.Thread(target=run, args=(slot,), daemon=True) for slot in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    return results


def test_two_workers_store_the_same_inbound_once(session, sid, monkeypatch):
    """두 프로세스의 일꾼이 같은 DB 에서 같은 받은 문자를 함께 읽어도 한 줄만 남는다(겹침 확인과 넣기가 한 쓰기 트랜잭션)."""
    connect(session, inbound_mode="known")
    person(session, sid)
    session.commit()
    item = text_in()

    stored = _side_by_side(monkeypatch, worker, "route", lambda: worker._store_inbound([item], OUR, as_utc(NOW), False))

    assert len(inbound_rows(session)) == 1
    assert sorted(len(result.new) for result in stored) == [0, 1]
    [row] = inbound_rows(session)
    assert len(details(session, row)) == 1


async def test_inbound_is_handed_to_inbox(session, sid, fake_provider, handed):
    """응대할 것(engage·notice)만 글 세션 줄에 넣는다. 기록만 하는 것(받지 않음·사진·기계 문자)은 넣지 않는다."""
    connect(session, inbound_mode="known")
    person(session, sid)
    session.commit()
    receive(fake_provider, text_in(pid="MGIN0001"), text_in(pid="MGIN0002", sender=STRANGER),
            Inbound(provider_id="MGIN0003", from_number=PHONE, body="사진", at=as_utc(NOW), has_media=True, to_number=OUR))

    await worker.tick(now=NOW)

    known, stranger, photo = inbound_rows(session)
    assert handed == [known.id]
    assert details(session, stranger) == [("admission", "blocked", "unknown_not_accepted")]
    assert details(session, photo) == [("admission", "blocked", "media_attached")] and photo.has_media is True


def test_inbox_enqueue_does_nothing_yet():
    assert inbox.enqueue(1) is None


async def test_inbound_off_records_only(session, sid, fake_provider, handed):
    connect(session)  # inbound_mode off
    who = person(session, sid)
    session.commit()
    receive(fake_provider, text_in())

    await worker.tick(now=NOW)

    [row] = inbound_rows(session)
    assert row.contact_id == who.id and details(session, row) == [("admission", "blocked", "inbound_off")] and handed == []


async def test_outside_test_mode_text_is_recorded_only(session, sid, fake_provider, handed):
    connect(session, inbound_mode="all", test_mode=True, allow_numbers_json=["010-0000-0188"])
    person(session, sid)
    session.commit()
    receive(fake_provider, text_in())

    await worker.tick(now=NOW)

    [row] = inbound_rows(session)
    assert row.caller_class == "outside_test" and details(session, row) == [("admission", "blocked", "outside_test")]
    assert handed == []


async def test_withheld_number_and_cut_body(session, sid, fake_provider, handed):
    connect(session, inbound_mode="all")
    session.commit()
    receive(fake_provider, text_in(sender=phone.NO_NUMBER, body="가" * 4000, body_cut=True))

    await worker.tick(now=NOW)

    [row] = inbound_rows(session)
    assert (row.peer_number, row.caller_class, row.schedule_id) == (None, "withheld", None)
    assert row.body == "가" * 4000 + worker.CUT_MARK


async def test_stop_word_marks_the_number_and_makes_one_confirmation(session, sid, fake_provider, fake_channel, handed):
    connect(session, inbound_mode="known", agent_sms="delegate")
    who = person(session, sid)
    session.commit()
    receive(fake_provider, text_in(body="수신거부"))

    await worker.tick(now=NOW)

    [row] = inbound_rows(session)
    [confirm] = out_rows(session, "dnc_confirm")
    assert outreach.is_do_not_contact(session, PHONE) and handed == []
    assert details(session, row) == [("admission", "noted", "stop_word")]
    assert (confirm.body, confirm.origin, confirm.status) == (gate.DNC_CONFIRM_TEXT, "agent", "accepted")
    assert (confirm.schedule_id, confirm.contact_id, confirm.reply_to_id) == (sid, who.id, row.id)
    assert fake_channel.delivered == [Handed("sms", confirm.id)]

    receive(fake_provider, text_in(body="수신거부"), text_in(body="수신거부 부탁드립니다", pid="MGIN0002"))  # 또 보내옴
    await worker.tick(now=NOW + timedelta(seconds=20))

    assert len(inbound_rows(session)) == 2 and len(out_rows(session, "dnc_confirm")) == 1  # 확인 문자는 표시마다 하나
    assert len(fake_channel.delivered) == 1


async def test_stop_confirmation_waits_for_approval_by_default(session, sid, fake_provider, fake_channel):
    connect(session, inbound_mode="off")  # 받지 않음이어도 수신 거부 말은 듣는다 · 문자 권한은 「승인 받기」
    person(session, sid)
    session.commit()
    receive(fake_provider, text_in(body="그만"))

    await worker.tick(now=NOW)

    [confirm] = out_rows(session, "dnc_confirm")
    assert outreach.is_do_not_contact(session, PHONE)
    assert confirm.status == "draft" and "승인" in confirm.fail_reason and fake_channel.delivered == []


async def test_stop_from_an_unlisted_number_marks_without_a_confirmation(session, sid, fake_provider, fake_channel):
    connect(session, inbound_mode="all", agent_sms="delegate")
    session.commit()
    receive(fake_provider, text_in(sender=STRANGER, body="수신거부"))

    await worker.tick(now=NOW)

    assert outreach.is_do_not_contact(session, STRANGER) and out_rows(session, "dnc_confirm") == []
    assert fake_channel.delivered == []


async def test_admission_trouble_keeps_the_stored_text_and_judges_it_again(session, sid, fake_provider, handed, monkeypatch,
                                                                           caplog):
    """받기 판정이 깨져도 받은 문자는 남고 다음 문자는 그대로 받는다 — 깨진 줄은 다음 바퀴에 저장된 글로 다시 판정받는다
    (한 번만: 판정이 된 줄은 다시 하지 않는다)."""
    caplog.set_level(logging.DEBUG)
    connect(session, inbound_mode="known")
    person(session, sid)
    session.commit()
    real = door.admit

    def admit(session, medium, number, **kw):
        if "깨짐" in kw["body"]:
            raise RuntimeError(f"boom {SENTINEL_PHONE}")
        return real(session, medium, number, **kw)

    monkeypatch.setattr(door, "admit", admit)
    receive(fake_provider, text_in(body="깨짐"), text_in(pid="MGIN0002"))

    assert (await worker.tick(now=NOW))["inbound"] == 2  # 판정이 깨진 줄도 새로 저장한 줄로 센다

    broken, fine = inbound_rows(session)
    assert (broken.body, broken.caller_class, details(session, broken)) == ("깨짐", None, [])
    assert handed == [fine.id] and worker.status()["last_error_kind"] == "RuntimeError"

    monkeypatch.setattr(door, "admit", real)  # 판정이 다시 된다
    await worker.tick(now=NOW + timedelta(seconds=20))
    await worker.tick(now=NOW + timedelta(seconds=40))

    broken = reread(session, broken)
    assert broken.caller_class == "contact" and details(session, broken) == [("admission", "allowed", "known_caller")]
    assert handed == [fine.id, broken.id] and len(details(session, fine)) == 1
    assert worker.status()["last_error_kind"] is None
    assert_clean(caplog)


async def test_lost_stop_word_is_judged_again_before_the_next_send(session, sid, fake_provider, fake_channel, monkeypatch):
    """「수신거부」의 판정이 깨졌으면 다음 바퀴에 다시 판정한다 — 그 바퀴에 때가 된 예약보다 먼저(번호가 표시돼 예약은 나가지
    않는다). 확인 문자도 한 번만."""
    connect(session, inbound_mode="known", agent_sms="delegate")
    who = person(session, sid)
    session.commit()
    real = door.admit

    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(door, "admit", broken)
    receive(fake_provider, text_in(body="수신거부"))

    await worker.tick(now=NOW)
    assert not outreach.is_do_not_contact(session, PHONE) and out_rows(session, "dnc_confirm") == []

    monkeypatch.setattr(door, "admit", real)
    planned = due(session, who, body="예약해 둔 안내", scheduled_at=NOW)
    session.commit()
    await worker.tick(now=NOW + timedelta(seconds=20))
    await worker.tick(now=NOW + timedelta(seconds=40))

    [row] = inbound_rows(session)
    [confirm] = out_rows(session, "dnc_confirm")
    assert outreach.is_do_not_contact(session, PHONE) and details(session, row) == [("admission", "noted", "stop_word")]
    assert (confirm.status, confirm.reply_to_id) == ("accepted", row.id)
    assert reread(session, planned).status == "draft"
    assert fake_channel.delivered == [Handed("sms", confirm.id)]


def _unjudged(session, pid: str, created: datetime) -> OutreachMessage:
    """판정이 깨진 채 남은 받은 줄(caller_class 없음 · 사건 없음)."""
    row = OutreachMessage(direction="in", channel="sms", status="received", origin="peer", peer_number=PHONE, body="내일 됩니다",
                          provider_message_id=pid, sent_at=created, created_at=created)
    session.add(row)
    session.flush()
    return row


async def test_judging_again_is_capped_oldest_first_and_old_rows_are_left_for_a_person(session, sid, fake_provider, handed,
                                                                                        monkeypatch):
    connect(session, inbound_mode="known")
    person(session, sid)
    old = _unjudged(session, "MGOLD", NOW - timedelta(seconds=worker.READMIT_MAX_AGE_S + 60))
    rows = [_unjudged(session, f"MGIN{i:04d}", NOW - timedelta(minutes=10 - i)) for i in range(3)]
    session.commit()
    monkeypatch.setattr(worker, "READMIT_PER_TICK", 2)
    receive(fake_provider)

    await worker.tick(now=NOW)
    assert handed == [rows[0].id, rows[1].id] and reread(session, rows[2]).caller_class is None
    assert worker.status()["inbound_unjudged"] == 1

    await worker.tick(now=NOW + timedelta(seconds=20))
    await worker.tick(now=NOW + timedelta(seconds=40))
    assert handed == [row.id for row in rows]
    assert reread(session, old).caller_class is None and details(session, old) == []
    assert worker.status()["inbound_unjudged"] == 1


def test_two_workers_never_judge_the_same_row_twice(session, sid, monkeypatch):
    """판정은 쓰기 트랜잭션 안에서 줄의 caller_class 를 다시 보고 한다 — 두 일꾼이 같은 줄을 함께 다시 판정해도 한 번."""
    connect(session, inbound_mode="known", agent_sms="delegate")
    person(session, sid)
    row = _unjudged(session, "MGIN0001", NOW - timedelta(minutes=1))
    row.body = "수신거부"
    session.commit()

    judged = _side_by_side(monkeypatch, door, "admit", lambda: worker._admit(row.id, as_utc(NOW)))

    assert sorted(result is None for result in judged) == [False, True]
    assert details(session, row) == [("admission", "noted", "stop_word")] and len(out_rows(session, "dnc_confirm")) == 1


async def test_inbound_poll_slows_down_when_nothing_is_expected(session, sid, fake_provider):
    """받는 범위가 「받지 않음」이고 최근 7일에 보낸 것이 없으면 60초마다, 아니면 20초마다."""
    conn = connect(session)
    who = person(session, sid)
    session.commit()
    asked = receive(fake_provider)

    for seconds in (0, 20, 40, 60, 80):
        await worker.tick(now=NOW + timedelta(seconds=seconds))
    assert len(asked) == 2  # 0초 · 60초

    conn.inbound_mode = "known"
    session.commit()
    for seconds in (100, 120):
        await worker.tick(now=NOW + timedelta(seconds=seconds))
    assert len(asked) == 4

    conn.inbound_mode = "off"
    message(session, who, status="delivered", claimed_at=NOW - timedelta(days=6))  # 엿새 전에 보낸 것이 있다
    session.commit()
    for seconds in (140, 160):
        await worker.tick(now=NOW + timedelta(seconds=seconds))
    assert len(asked) == 6


# ── 한 바퀴의 상한 ────────────────────────────────────────────────────


@pytest.mark.real_channel("sms")
async def test_tick_caps_provider_requests(session, sid, fake_provider):
    connect(session, agent_sms="delegate", limits_json={"per_contact_sms_daily": 100, "daily_sms_total": 100})
    who = person(session, sid)
    for name, number in (("이철근", OTHER_PHONE), ("최설비", STRANGER), ("정전기", "01000000166")):
        person(session, sid, number, name=name)
    for i in range(12):
        due(session, who, body=f"예약 {i}")
        sent(session, who, pid=f"FAKE-S{i:02d}", body=f"보낸 글 {i}")
    session.commit()
    # 주소록의 세 사람이 한꺼번에 수신 거부를 보냄 — 확인 문자도 같은 상한 안에서만 나간다
    receive(fake_provider, *[text_in(sender=number, pid=f"MGIN{i:04d}", body="수신거부")
                             for i, number in enumerate((OTHER_PHONE, STRANGER, "01000000166"))])

    result = await worker.tick(now=NOW)

    log = fake_provider.log
    assert (result["due"], log.count("received")) == (worker.DUE_PER_TICK, 1)
    assert log.count("send_message") == worker.DUE_PER_TICK + worker.CONFIRMS_PER_TICK
    assert 1 <= log.count("message_status") <= worker.STATUS_PER_TICK
    assert result["requests"] <= worker.MAX_REQUESTS_PER_TICK == 20  # received 는 가장 많이 쓰는 수(9)로 센다
    assert len(log) <= worker.MAX_REQUESTS_PER_TICK - provider.RECEIVED_MAX_REQUESTS + 1
    confirms = out_rows(session, "dnc_confirm")
    assert [row.status for row in confirms] == ["accepted", "accepted", "draft"]  # 셋째는 초안으로 남아 사람이 보낸다
    assert confirms[2].fail_reason == worker.CONFIRM_HELD

    for step in range(1, 4):  # 남은 것은 다음 바퀴들이 이어서 — 바퀴마다 같은 상한
        before = len(fake_provider.log)
        again = await worker.tick(now=NOW + timedelta(seconds=20 * step))
        assert again["requests"] <= 20 and len(fake_provider.log) - before <= 12
    keys = [req.idempotency_key for req in fake_provider.sent]
    assert len(keys) == len(set(keys)) == 12 + 2  # 예약 12건 + 확인 2건 — 어느 것도 두 번 나가지 않았다


async def test_inbound_rows_per_tick_are_capped_and_none_is_lost(session, sid, fake_provider, monkeypatch):
    connect(session, inbound_mode="known")
    person(session, sid)
    session.commit()
    monkeypatch.setattr(worker, "INBOUND_ROWS_PER_TICK", 3)
    receive(fake_provider, *[text_in(pid=f"MGIN{i:04d}", body=f"답 {i}") for i in range(7)])

    await worker.tick(now=NOW)
    assert len(inbound_rows(session)) == 3 and cursor(session) is None  # 다 넣지 못했으면 커서를 당기지 않는다

    await worker.tick(now=NOW + timedelta(seconds=20))
    await worker.tick(now=NOW + timedelta(seconds=40))
    assert [row.provider_message_id for row in inbound_rows(session)] == [f"MGIN{i:04d}" for i in range(7)]
    assert cursor(session) is not None


async def test_text_that_cannot_be_stored_holds_the_cursor_for_a_while_then_is_skipped(session, sid, fake_provider,
                                                                                         monkeypatch, caplog):
    """받은 문자를 저장하지 못하면(DB 가 바쁨 …) 커서를 당기지 않고 다음 바퀴에 다시 받는다 — 끝없이는 아니다:
    INBOUND_HOLD_MAX 바퀴를 넘기면 그 줄을 건너뛰고(센다) 나아간다."""
    caplog.set_level(logging.DEBUG)
    connect(session, inbound_mode="known")
    person(session, sid)
    session.commit()
    monkeypatch.setattr(worker, "INBOUND_HOLD_MAX", 2)
    real = worker._insert

    def insert(session, item, at):
        if item.provider_id == "MGIN0002":
            raise RuntimeError(f"boom {SENTINEL_PHONE}")
        return real(session, item, at)

    monkeypatch.setattr(worker, "_insert", insert)
    receive(fake_provider, text_in(pid="MGIN0001"), text_in(pid="MGIN0002"), text_in(pid="MGIN0003"))

    for step in range(2):
        result = await worker.tick(now=NOW + timedelta(seconds=20 * step))
        assert result["error"] == "RuntimeError" and cursor(session) is None
        assert [row.provider_message_id for row in inbound_rows(session)] == ["MGIN0001"]  # 깨진 줄에서 멈춘다
    assert worker.status()["inbound_failed"] == 0 and worker.status()["quiet_until"] is None

    await worker.tick(now=NOW + timedelta(seconds=40))  # 이제 그 줄을 건너뛴다

    assert [row.provider_message_id for row in inbound_rows(session)] == ["MGIN0001", "MGIN0003"]
    assert cursor(session) is not None and worker.status()["inbound_failed"] == 1
    assert_clean(caplog)


# ── 오류·연결 없음 ────────────────────────────────────────────────────


async def test_worker_survives_provider_errors(session, sid, fake_provider, fake_channel, caplog):
    caplog.set_level(logging.DEBUG)
    connect(session, inbound_mode="known")
    who = person(session, sid)
    row = sent(session, who)
    session.commit()
    fake_provider.inbox.append(text_in(at=NOW + timedelta(minutes=19)))
    fake_provider.fail = ProviderFailed("server", f"오류 {SENTINEL_PHONE} {SENTINEL_KEY} {BODY}", 500, maybe_sent=True)

    result = await worker.tick(now=NOW)  # 예외가 새지 않는다

    assert result["error"] == "server" and worker.status()["last_error_kind"] == "server"
    assert fake_provider.log == ["message_status"]  # 연결이 안 되면 그 바퀴의 남은 요청을 하지 않는다
    assert reread(session, row).status == "accepted" and inbound_rows(session) == []
    assert_clean(caplog, BODY)

    async def broken(since):
        raise RuntimeError(f"boom {SENTINEL_PHONE} {SENTINEL_KEY}")

    fake_provider.fail, fake_provider.received = None, broken
    later = NOW + timedelta(minutes=10)
    result = await worker.tick(now=later)  # 가짜가 무엇을 던지든

    assert result["error"] == "RuntimeError" and worker.status()["last_error_kind"] == "RuntimeError"
    assert_clean(caplog, BODY)

    del fake_provider.received  # 다시 정상
    result = await worker.tick(now=later + timedelta(minutes=10))
    assert result["error"] is None and len(inbound_rows(session)) == 1 and worker.status()["last_error_kind"] is None


async def test_provider_trouble_quiets_the_worker_for_a_while(session, sid, fake_provider, fake_channel):
    """제공사가 안 되면(연결·키·잦은 요청) 조금씩 길게 쉰다 — 그동안은 예약도 내보내지 않는다(실패로 닫히지 않게)."""
    connect(session)
    who = person(session, sid)
    waiting = sent(session, who)
    session.commit()
    fake_provider.fail = ProviderFailed("rate_limited", "잦음", 429, retry_after_s=90)

    await worker.tick(now=NOW)
    assert worker.status()["quiet_until"] == as_utc(NOW + timedelta(seconds=90)).isoformat()

    row = due(session, who, body="쉬는 동안 때가 된 글")
    session.commit()
    result = await worker.tick(now=NOW + timedelta(seconds=60))
    assert result["skipped"] == "quiet" and fake_provider.log == ["message_status"] and fake_channel.delivered == []
    assert reread(session, row).status == "scheduled" and reread(session, waiting).checks == 0

    fake_provider.fail = None
    result = await worker.tick(now=NOW + timedelta(seconds=100))
    assert result["skipped"] is None and fake_channel.delivered == [Handed("sms", row.id)]
    assert worker.status()["quiet_until"] is None


async def test_repeated_trouble_backs_off_up_to_five_minutes(session, sid, fake_provider):
    connect(session)
    person(session, sid)
    session.commit()
    fake_provider.fail = ProviderFailed("network", "연결 실패")
    at, waits = NOW, []

    for _ in range(7):
        await worker.tick(now=at)
        until = datetime.fromisoformat(worker.status()["quiet_until"])
        waits.append(int((until - as_utc(at)).total_seconds()))
        at = until

    assert waits == [20, 40, 80, 160, 300, 300, 300] and fake_provider.log == ["received"] * 7


MANY = {"per_contact_sms_daily": 100, "daily_sms_total": 100}


@pytest.mark.real_channel("sms")
@pytest.mark.parametrize(("failure", "closed", "kind"), [
    (ProviderFailed("network", "연결 실패"), "failed", "network"),
    (ProviderFailed("bad_key", "키", 401), "failed", "bad_key"),
    (ProviderFailed("rate_limited", "잦음", 429, retry_after_s=90), "failed", "rate_limited"),
    (ProviderFailed("server", "오류", 500, maybe_sent=True), "unconfirmed", "unsure"),
])
async def test_send_failure_stops_the_due_rows_and_backs_off(session, sid, fake_provider, failure, closed, kind):
    """보내기가 제공사 쪽 까닭으로 실패하거나 결과를 모르면 그 바퀴의 남은 예약을 넣지 않고 쉰다 — 한 번의 끊김이 때가 된
    예약을 모두 실패·확인 필요로 닫지 않는다."""
    connect(session, limits_json=MANY)
    who = person(session, sid)
    rows = [due(session, who, body=f"예약 {i}") for i in range(3)]
    waiting = sent(session, who)
    session.commit()
    fake_provider.fail = failure

    result = await worker.tick(now=NOW)

    assert [reread(session, row).status for row in rows] == [closed, "scheduled", "scheduled"]
    assert fake_provider.log == ["send_message"] and result["error"] == kind  # 조회·받기도 그 바퀴에는 하지 않는다
    assert reread(session, waiting).checks == 0
    assert worker.status()["quiet_until"] == as_utc(NOW + timedelta(seconds=worker.TICK_S)).isoformat()


@pytest.mark.real_channel("sms")
async def test_after_a_send_failure_reads_go_first_and_sending_waits_for_them(session, sid, fake_provider, monkeypatch):
    """쉰 뒤의 바퀴는 읽기부터 — 들어온 문자를 읽을 때가 아니어도 읽어 보고, 되면 그때 넣는다."""
    connect(session, limits_json=MANY)
    who = person(session, sid)
    monkeypatch.setattr(worker, "INBOUND_S", 1000.0)  # 들어온 문자는 이 시험 동안 읽을 때가 아니다(첫 바퀴만 빼고)
    monkeypatch.setattr(worker, "INBOUND_IDLE_S", 1000.0)
    session.commit()
    assert (await worker.tick(now=NOW - timedelta(seconds=10)))["skipped"] is None and fake_provider.log == ["received"]
    rows = [due(session, who, body=f"예약 {i}") for i in range(3)]
    session.commit()
    fake_provider.fail = ProviderFailed("network", "연결 실패")
    fake_provider.log.clear()
    await worker.tick(now=NOW)
    assert fake_provider.log == ["send_message"]

    fake_provider.log.clear()
    await worker.tick(now=NOW + timedelta(seconds=20))  # 쉬고 나서도 아직 안 된다 — 읽기만 해 보고 보내지 않는다
    assert fake_provider.log == ["received"]
    assert [reread(session, row).status for row in rows] == ["failed", "scheduled", "scheduled"]

    fake_provider.fail = None  # 돌아옴
    fake_provider.log.clear()
    await worker.tick(now=NOW + timedelta(seconds=60))
    assert fake_provider.log == ["received", "send_message", "send_message"]
    assert [reread(session, row).status for row in rows] == ["failed", "accepted", "accepted"]
    assert worker.status()["quiet_until"] is None and worker.status()["last_error_kind"] is None


async def test_gate_refusals_and_our_own_send_failures_are_not_provider_trouble(session, sid, fake_provider, fake_channel):
    """문이 막은 것(수신 거부 …)과 통로가 보내기 전에 스스로 거른 것은 제공사 탓이 아니다 — 쉬지 않고 나머지를 넣는다."""
    connect(session, limits_json=MANY)
    refused = due(session, person(session, sid))
    outreach.mark_do_not_contact(session, PHONE, reason="전화로 요청")
    other = person(session, sid, OTHER_PHONE, name="이철근")
    rows = [due(session, other, body=f"예약 {i}") for i in range(2)]
    session.commit()
    fake_channel.result = Delivered("failed", fail_code=sms.NOT_REACHABLE)

    result = await worker.tick(now=NOW)

    assert result["due"] == 3 and reread(session, refused).status == "draft"
    assert [reread(session, row).status for row in rows] == ["failed", "failed"]
    assert worker.status()["quiet_until"] is None and result["error"] is None


@pytest.mark.real_channel("sms")
async def test_confirmation_send_failure_also_backs_off(session, sid, fake_provider):
    """수신 거부 확인 문자도 보내기다 — 제공사 쪽 까닭으로 실패하면 쉬고, 그 바퀴의 다음 확인 문자는 초안으로 남는다."""
    connect(session, inbound_mode="known", agent_sms="delegate", limits_json=MANY)
    person(session, sid)
    person(session, sid, OTHER_PHONE, name="이철근")
    session.commit()
    receive(fake_provider, text_in(body="수신거부"), text_in(sender=OTHER_PHONE, pid="MGIN0002", body="수신거부"))

    async def refused(req):
        fake_provider._called("send_message")
        raise ProviderFailed("network", "연결 실패")

    fake_provider.send_message = refused

    result = await worker.tick(now=NOW)

    first, second = out_rows(session, "dnc_confirm")
    assert (first.status, second.status, second.fail_reason) == ("failed", "draft", worker.CONFIRM_HELD)
    assert fake_provider.log.count("send_message") == 1 and result["error"] == "network"
    assert worker.status()["quiet_until"] is not None


@pytest.mark.parametrize("state", ["missing", "unknown", "failed", "unreadable_key"])
async def test_no_usable_connection_means_nothing_happens(session, sid, fake_channel, state, monkeypatch):
    """연결이 없거나 ok 가 아니면 아무것도 하지 않는다 — 예약 줄도 그대로 둔다(연결이 돌아오면 그때 검사받는다)."""
    calls = []
    if state == "unreadable_key":
        connect(session)  # secret_ciphertext 가 암호문이 아니다 — 실제 client_for 가 bad_key
    else:
        monkeypatch.setattr(provider, "client_for", lambda row: calls.append("client") or None)
        if state != "missing":
            connect(session, status=state)
    who = person(session, sid)
    row = due(session, who)
    stuck = message(session, who, status="sending", claimed_at=NOW - timedelta(hours=1), body="남은 글")
    session.commit()

    result = await worker.tick(now=NOW)

    assert result["skipped"] == {"missing": "no_connection", "unknown": "not_ok", "failed": "not_ok",
                                 "unreadable_key": "bad_key"}[state]
    assert calls == [] and fake_channel.delivered == []
    assert reread(session, row).status == "scheduled" and reread(session, stuck).status == "sending"
    assert trail(session, row) == []


async def test_tick_without_a_database_does_not_raise(monkeypatch):
    from app import db

    monkeypatch.setattr(db, "_engine", None)
    result = await worker.tick(now=NOW)
    assert result["error"] is not None and worker.status()["last_error_kind"] == result["error"]


async def test_worker_holds_no_database_lock_while_the_provider_is_called(session, sid, fake_provider):
    connect(session, inbound_mode="known")
    who = person(session, sid)
    sent(session, who)
    session.commit()
    fake_provider.inbox.append(text_in())
    probed = []
    real = fake_provider._called

    def called(name):
        with closing(sqlite3.connect(db_path(), timeout=0.1)) as other:  # 쓰기 잠금이 잡혀 있으면 여기서 실패한다
            other.execute("BEGIN IMMEDIATE")
            other.execute("COMMIT")
        probed.append(name)
        real(name)

    fake_provider._called = called

    result = await worker.tick(now=NOW)

    assert result["error"] is None and probed == ["message_status", "received"]


# ── 상태·띄우기·멈추기 ────────────────────────────────────────────────


async def test_status_reports_last_run_times(session, sid, fake_provider, fake_channel):
    empty = worker.status()
    assert empty == {"running": False, "last_tick_at": None, "last_due_at": None, "last_status_poll_at": None,
                     "last_inbound_poll_at": None, "inbound_truncated": 0, "inbound_truncated_at": None, "inbound_skipped": 0,
                     "inbound_redated": 0, "inbound_other_sender": 0, "inbound_failed": 0, "last_error_kind": None,
                     "quiet_until": None, "off_reason": None, "inbound_unjudged": 0}
    connect(session)
    who = person(session, sid)
    due(session, who)
    sent(session, who)
    session.commit()

    await worker.tick(now=NOW)

    at = as_utc(NOW).isoformat()
    state = worker.status()
    assert (state["last_tick_at"], state["last_due_at"], state["last_status_poll_at"], state["last_inbound_poll_at"]) == (at,) * 4
    text = repr(state)
    assert PHONE not in text and SENTINEL_KEY not in text and OUR not in text


async def test_overlapping_tick_is_skipped(session, sid, fake_provider):
    connect(session)
    session.commit()
    inside = []

    async def received(since):
        inside.append(await worker.tick(now=NOW))  # 한 바퀴가 도는 동안 또 불림
        return Received(items=[], fetched_at=as_utc(NOW))

    fake_provider.received = received

    await worker.tick(now=NOW)

    assert [result["skipped"] for result in inside] == ["busy"]


async def test_start_twice_is_one_worker_and_stop_ends_it(session, monkeypatch):
    ticks = []

    async def one_tick(now=None):
        ticks.append(now)
        return {}

    monkeypatch.setattr(worker, "tick", one_tick)
    start = worker.start.__wrapped__  # conftest 가 덮기 전의 진짜 start
    try:
        start()
        first = worker._task
        start()  # 두 번 띄워도 하나
        assert worker._task is first and worker.status()["running"] is True
        for _ in range(500):  # 첫 바퀴를 기다린다(길어야 5초)
            if ticks:
                break
            await asyncio.sleep(0.01)
        assert ticks == [None]
    finally:
        began = time.monotonic()
        await worker.stop()
    assert first.done() and not first.cancelled() and worker.status()["running"] is False
    assert time.monotonic() - began < 3.0 and ticks == [None]  # 쉬는 중이면 곧바로 멈춘다(STOP_WAIT_S 를 다 쓰지 않는다)
    await worker.stop()  # 떠 있지 않아도 괜찮다


def _start_lines(caplog) -> list[tuple[int, str]]:
    return [(record.levelno, record.getMessage()) for record in caplog.records if record.name == worker.__name__]


@pytest.mark.parametrize(("env", "reason"), [
    ({"CHRONOS_OUTREACH_WORKER": "off"}, "disabled"),
    ({"CHRONOS_OUTREACH_WORKER": "0"}, "disabled"),
    ({"CHRONOS_OUTREACH_WORKER": "false"}, "disabled"),
    ({"CHRONOS_OUTREACH_WORKER": " OFF "}, "disabled"),
    ({"CHRONOS_OUTREACH_WORKER": "of"}, "disabled"),  # 모르는 값은 끈다(실제 문자를 보낼 수 있는 일꾼이다)
    ({"CHRONOS_HARNESS_SANDBOX": "1"}, "sandbox"),
    ({"CHRONOS_HARNESS_SANDBOX": "1", "CHRONOS_OUTREACH_WORKER": "on"}, "sandbox"),
])
async def test_switch_keeps_the_worker_off(session, monkeypatch, caplog, env, reason):
    """CHRONOS_OUTREACH_WORKER 가 off·0·false(또는 모르는 값)이거나 모래상자 프로세스면 일꾼을 띄우지 않는다 — 시작 로그
    한 줄과 status 의 off_reason 으로 까닭을 남긴다."""
    caplog.set_level(logging.DEBUG)
    monkeypatch.delenv("CHRONOS_HARNESS_SANDBOX", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    ran = []

    async def run(stop, started):
        ran.append(started)

    monkeypatch.setattr(worker, "_run", run)
    try:
        worker.start.__wrapped__()
        assert worker._task is None
    finally:
        await worker.stop()

    assert ran == [] and worker.status()["running"] is False and worker.status()["off_reason"] == reason
    assert _start_lines(caplog) == [(logging.INFO, f"연락 일꾼: 띄우지 않습니다 ({reason})")]


@pytest.mark.parametrize("value", [None, "on", "ON", "1", "true"])
async def test_switch_on_or_unset_starts_the_worker(session, monkeypatch, caplog, value):
    caplog.set_level(logging.DEBUG)
    monkeypatch.delenv("CHRONOS_HARNESS_SANDBOX", raising=False)
    if value is not None:
        monkeypatch.setenv("CHRONOS_OUTREACH_WORKER", value)
    ran = []

    async def run(stop, started):  # 고리를 돌리지 않는다 — 띄웠는지만 본다
        ran.append(started)

    monkeypatch.setattr(worker, "_run", run)
    try:
        worker.start.__wrapped__()
        assert worker._task is not None
    finally:
        await worker.stop()

    assert len(ran) == 1 and worker.status()["off_reason"] is None
    assert _start_lines(caplog) == [(logging.INFO, "연락 일꾼: 띄웁니다")]


async def test_started_worker_first_closes_rows_left_sending_before_it_started(session, sid, monkeypatch):
    connect(session)
    who = person(session, sid)
    left = message(session, who, status="sending", claimed_at=datetime.now(UTC) - timedelta(minutes=10))
    pressed = message(session, who, status="sending", claimed_at=datetime.now(UTC) + timedelta(hours=1), body="뜬 뒤에 누른 글")
    young = message(session, who, status="sending", claimed_at=datetime.now(UTC) - timedelta(seconds=5), body="다른 쪽이 보내는 글")
    session.commit()
    ticks = []

    async def one_tick(now=None):
        ticks.append(reread(session, left).status)  # 첫 바퀴보다 정리가 먼저다

    monkeypatch.setattr(worker, "tick", one_tick)
    try:
        worker.start.__wrapped__()
        for _ in range(500):
            if ticks:
                break
            await asyncio.sleep(0.01)
    finally:
        await worker.stop()

    assert ticks == ["unconfirmed"] and reread(session, pressed).status == "sending"
    assert reread(session, young).status == "sending"
    assert details(session, left) == [("server_restart", "noted", worker.RESTARTED)]


async def test_stop_lets_the_current_tick_finish(session, monkeypatch):
    steps = []

    async def slow_tick(now=None):
        steps.append("in")
        await asyncio.sleep(0.1)
        steps.append("out")

    monkeypatch.setattr(worker, "tick", slow_tick)
    try:
        worker.start.__wrapped__()
        for _ in range(500):
            if steps:
                break
            await asyncio.sleep(0.01)
    finally:
        await worker.stop()
    assert steps == ["in", "out"]


async def test_stop_cancels_a_tick_that_takes_too_long(session, monkeypatch):
    steps = []

    async def stuck_tick(now=None):
        steps.append("in")
        await asyncio.sleep(5)  # 끝이 있는 기다림 — 멈추기가 끊는다
        steps.append("out")

    monkeypatch.setattr(worker, "tick", stuck_tick)
    monkeypatch.setattr(worker, "STOP_WAIT_S", 0.05)
    try:
        worker.start.__wrapped__()
        task = worker._task
        for _ in range(500):
            if steps:
                break
            await asyncio.sleep(0.01)
    finally:
        began = time.monotonic()
        await worker.stop()
    assert steps == ["in"] and task.cancelled() and time.monotonic() - began < 3.0  # 5초짜리 바퀴를 기다리지 않았다
    assert worker.status()["running"] is False


async def test_run_loop_stops_itself_when_it_spins(session, monkeypatch):
    """쉬지 못하고 헛도는 고리는 스스로 멈춘다(바퀴마다 걸린 시간을 재서 — 끝없이 돌며 무엇을 쌓지 않게)."""
    calls = []

    async def tick(now=None):
        calls.append(1)
        if len(calls) > 50:
            raise Runaway("일꾼 고리가 멈추지 않습니다")

    async def no_pause(stop, seconds):
        return None

    monkeypatch.setattr(worker, "tick", tick)
    monkeypatch.setattr(worker, "_pause", no_pause)

    await worker._run(asyncio.Event(), datetime.now(UTC))

    assert len(calls) == worker.MAX_FAST_PASSES and worker.status()["last_error_kind"] == "spinning"
    assert worker.status()["running"] is False


async def test_run_loop_keeps_going_after_a_tick_error(session, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    calls, stop = [], asyncio.Event()

    async def tick(now=None):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError(f"boom {SENTINEL_PHONE}")
        stop.set()

    async def brief(stop, seconds):
        await asyncio.sleep(0)

    monkeypatch.setattr(worker, "tick", tick)
    monkeypatch.setattr(worker, "_pause", brief)

    await worker._run(stop, datetime.now(UTC))

    assert len(calls) == 2
    assert_clean(caplog)


def test_app_lifespan_starts_and_stops_the_worker(monkeypatch):
    calls = []

    async def stop():
        calls.append("stop")

    monkeypatch.setattr(worker, "start", lambda: calls.append("start"))
    monkeypatch.setattr(worker, "stop", stop)

    with TestClient(app):
        assert calls == ["start"]
    assert calls == ["start", "stop"]


def test_real_worker_runs_inside_the_app_against_an_empty_database(monkeypatch):
    """알림 연결이 없는 DB(키를 넣기 전의 서버)에서 진짜 일꾼이 떠도 뜨고 닫는 데 걸리지 않고, 아무것도 하지 않는다."""
    monkeypatch.setattr(worker, "start", worker.start.__wrapped__)
    monkeypatch.setattr(provider, "client_for", lambda row: pytest.fail("연결이 없는데 제공사 클라이언트를 만들었습니다"))

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200  # 일꾼이 떠 있어도 앱은 곧바로 답한다
        for _ in range(250):  # 첫 바퀴를 기다린다(길어야 5초)
            if worker.status()["last_tick_at"]:
                break
            time.sleep(0.02)
        state = worker.status()
        assert state["running"] is True and state["last_tick_at"] and state["last_inbound_poll_at"] is None
        assert state["last_error_kind"] is None
        closing = time.monotonic()

    assert worker.status()["running"] is False and time.monotonic() - closing < 3.0  # 닫는 데 STOP_WAIT_S 를 쓰지 않는다


def test_importing_the_worker_registers_no_channel_but_starting_it_does():
    """통로는 일꾼을 띄울 때(start) 등록된다 — 모듈을 불러오는 것만으로는 진짜 통로가 생기지 않는다."""
    code = ("import asyncio, sys\nfrom app.outreach import worker\nfrom app.outreach.harness import registry\n"
            "print(registry.registered(), 'app.outreach.channels' in sys.modules)\n"
            "async def main():\n    worker.start()\n    print(registry.registered())\n    await worker.stop()\n"
            "asyncio.run(main())")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=True,
                          cwd=Path(__file__).parents[2])
    assert done.stdout.split("\n")[:2] == ["[] False", "['sms']"]
