"""진단 칸 둘과 연락 사용량 요약(Task 112).

번호는 모두 가상이다(이름표의 010-0000-0199 = 정리한 꼴 01000000199). 셈은 저장소의 한 규칙(claim 된 순간, 서울 날짜)을 따른다.
"""

import re
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, insert, update
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.db import close_db, init_db
from app.store import outreach, outreach_usage
from app.store.outreach_usage import KindUsage, UsageSummary
from app.store.tables_outreach import (
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
    OutreachUsage,
    VoiceSettings,
)

KST = ZoneInfo("Asia/Seoul")
PHONE = "01000000199"
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=KST)  # 서울 11-24 오전
TODAY = datetime(2026, 11, 24, 0, 0, tzinfo=KST)  # 서울 11-24 자정(= UTC 11-23 15:00)


def _message(session: Session, **kw) -> OutreachMessage:
    row = OutreachMessage(**{"direction": "out", "channel": "sms", "origin": "user", "body": "내일 타설 가능하신가요",
                             "peer_number": PHONE, "status": "accepted", "claimed_at": TODAY + timedelta(hours=9),
                             **kw})
    session.add(row)
    session.flush()
    return row


def _call(session: Session, **kw) -> OutreachCall:
    row = OutreachCall(**{"origin": "user", "purpose": "타설 일정 확인", "peer_number": PHONE, "status": "completed",
                          "claimed_at": TODAY + timedelta(hours=9), **kw})
    session.add(row)
    session.flush()
    return row


def _usage_at_nine(session: Session) -> None:
    """add_usage 는 지금 시각을 찍는다 — 시험의 「오늘」(서울 11-24 09:00)로 옮긴다."""
    session.execute(update(OutreachUsage).values(at=TODAY + timedelta(hours=9)))


def _old_table_ddl(table, engine) -> str:
    """Task 61 이 만든 모양(진단 칸 없음) 그대로."""
    ddl = str(CreateTable(table).compile(dialect=engine.dialect))
    old = "\n".join(line for line in ddl.splitlines() if "last_diagnosis_json" not in line)
    return re.sub(r",\s*\n\)", "\n)", old)  # 마지막 칸이었으므로 앞 줄의 쉼표도 뺀다


# ── 진단 칸 ─────────────────────────────────────────────────────────


def test_db_made_by_task_61_gets_the_two_diagnosis_columns(tmp_path):
    """진단 칸이 없던 notify_connections·voice_settings(줄 하나씩) → init_db → 두 칸이 더해지고 줄은 그대로, 값은 NULL."""
    path = tmp_path / "data" / "chronos.db"  # 시험 환경의 CHRONOS_DATA_DIR(tests/conftest.py)
    path.parent.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql(_old_table_ddl(NotifyConnection.__table__, engine))
        conn.exec_driver_sql(_old_table_ddl(VoiceSettings.__table__, engine))
        conn.execute(insert(NotifyConnection.__table__).values(
            id=1, name="기본", base_url="https://b.invalid", secret_ciphertext="x", secret_last4="2222",
            account_id="b", is_default=True))
        conn.execute(insert(VoiceSettings.__table__).values(connection_id=1, provider="openai", model="m"))
    engine.dispose()

    init_db()
    close_db()

    with closing(sqlite3.connect(path)) as db:
        for table in ("notify_connections", "voice_settings"):
            columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
            assert columns[-1] == "last_diagnosis_json"
        assert db.execute("SELECT name, last_diagnosis_json FROM notify_connections").fetchone() == ("기본", None)
        assert db.execute("SELECT provider, last_diagnosis_json FROM voice_settings").fetchone() == ("openai", None)


def test_db_made_before_the_agent_number_column_gains_it_and_keeps_its_rows(tmp_path):
    """Task 112 까지의 voice_settings(agent_number 칸 없음, 줄 하나) → init_db → 칸이 더해지고 줄은 그대로, 값은 NULL(Task 90)."""
    path = tmp_path / "data" / "chronos.db"
    path.parent.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{path}")
    ddl = str(CreateTable(VoiceSettings.__table__).compile(dialect=engine.dialect))
    old = "\n".join(line for line in ddl.splitlines() if not line.strip().startswith("agent_number "))
    assert "agent_number" not in old and "dashboard_agent_id" in old
    with engine.begin() as conn:
        conn.exec_driver_sql(old)
        conn.execute(insert(VoiceSettings.__table__).values(connection_id=1, provider="google", secret_last4="7777",
                                                            model="m", last_diagnosis_json={"ran_at": "x"}))
    engine.dispose()

    init_db()
    close_db()

    with closing(sqlite3.connect(path)) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(voice_settings)")]
        assert "agent_number" in columns and len(columns) == len(VoiceSettings.__table__.columns)
        assert db.execute("SELECT provider, secret_last4, model, agent_number FROM voice_settings").fetchall() == [
            ("google", "7777", "m", None)]
        assert db.execute("SELECT last_diagnosis_json FROM voice_settings").fetchone()[0] == '{"ran_at": "x"}'


def test_diagnosis_columns_store_and_read_back_a_dict(session):
    diagnosis = {"ran_at": "2026-11-24T01:00:00+00:00", "real": False,
                 "steps": [{"id": "P1", "label": "발신번호", "ok": True, "skipped": False, "detail": "승인 1개",
                            "latency_ms": 120, "notes": []}]}
    conn = NotifyConnection(name="기본", base_url="https://b.invalid", secret_ciphertext="x", secret_last4="2222",
                            account_id="b")
    session.add(conn)
    session.flush()
    assert conn.last_diagnosis_json is None
    conn.last_diagnosis_json = diagnosis
    session.add(VoiceSettings(connection_id=conn.id, last_diagnosis_json=diagnosis))
    session.commit()
    session.expire_all()
    assert session.get(NotifyConnection, conn.id).last_diagnosis_json == diagnosis
    assert session.get(VoiceSettings, conn.id).last_diagnosis_json == diagnosis


def test_diagnosis_column_docs_say_masked_text_only():
    for table in (NotifyConnection.__table__, VoiceSettings.__table__):
        column = table.c.last_diagnosis_json
        assert column.nullable and column.default is None
        assert "masked text only, no key, no number" in column.comment


# ── 사용량 요약 ─────────────────────────────────────────────────────


def test_empty_db_gives_zeros_and_no_cost(session):
    assert outreach_usage.summary(session, days=7, now=NOW) == UsageSummary(
        sms=0, long=0, kakao=0, auto_replies=0, call_seconds=0, calls_placed=0, calls_answered=0, calls_rejected=0,
        by_kind={}, provider_cost=None)


def test_summary_counts_sms_long_kakao_and_auto_replies(session):
    _message(session, length_kind="sms")
    _message(session, length_kind="long")
    _message(session, length_kind="long", status="delivered")
    _message(session, status="failed")  # 차지한 뒤 실패해도 센다(셈 규칙 하나)
    _message(session, channel="kakao", fallback_sms=True, length_kind="sms")  # 문자로 대신 나간 카카오톡 → 문자
    _message(session, channel="kakao", length_kind="long")  # 카카오톡은 장문 셈에 들지 않는다
    _message(session, kind="auto_reply")
    _message(session, kind="notice")
    # 세지 않는 것: 차지하지 않은 줄(초안·시험 모드·근무시간), 받은 문자
    _message(session, status="draft", claimed_at=None)
    _message(session, status="blocked_test", claimed_at=None, length_kind="long")
    _message(session, direction="in", origin="peer", status="received", claimed_at=None)
    session.commit()

    got = outreach_usage.summary(session, days=1, now=NOW)
    assert (got.sms, got.long, got.kakao, got.auto_replies) == (7, 2, 1, 2)
    # 상한이 세는 수와 같다(store.outreach.sent_count 와 한 규칙)
    day = NOW.date()
    assert got.sms == outreach.sent_count(session, "sms", day)
    assert got.kakao == outreach.sent_count(session, "kakao", day)
    assert got.auto_replies == len(outreach.auto_replies(session, PHONE, TODAY))


def test_days_window_ends_at_seoul_midnight(session):
    _message(session, claimed_at=TODAY - timedelta(seconds=1))  # 서울 11-23 23:59:59 = UTC 11-23 14:59:59
    _message(session, claimed_at=TODAY)  # 서울 11-24 00:00
    _message(session, claimed_at=TODAY - timedelta(days=6))  # 서울 11-18 00:00 — 7일 창의 첫날
    _message(session, claimed_at=TODAY - timedelta(days=6, seconds=1))  # 서울 11-17 — 창 밖
    _message(session, claimed_at=TODAY + timedelta(days=1))  # 서울 11-25 — 아직 오지 않은 날
    _call(session, claimed_at=TODAY - timedelta(seconds=1), duration_s=30)
    _call(session, claimed_at=TODAY, duration_s=40)
    session.commit()

    one = outreach_usage.summary(session, days=1, now=NOW)
    assert (one.sms, one.calls_placed, one.call_seconds) == (1, 1, 40)
    # now 가 UTC 로 와도 「오늘」은 서울 날짜(UTC 11-23 16:00 = 서울 11-24 01:00)
    assert outreach_usage.summary(session, days=1, now=TODAY.astimezone(UTC) + timedelta(hours=1)) == one
    week = outreach_usage.summary(session, days=7, now=NOW)
    assert (week.sms, week.calls_placed, week.call_seconds) == (3, 2, 70)
    total = sum(outreach.sent_count(session, "sms", NOW.date() - timedelta(days=n)) for n in range(7))
    assert week.sms == total


def test_days_must_be_positive(session):
    with pytest.raises(ValueError):
        outreach_usage.summary(session, days=0, now=NOW)


def test_call_seconds_and_answered_rejected(session):
    _call(session, duration_s=95)
    _call(session, status="no_answer", duration_s=None)
    _call(session, status="failed", duration_s=None)  # 차지한 뒤 실패해도 건 통화로 센다
    _call(session, status="blocked_hours", claimed_at=None, duration_s=None)  # 걸지 않음 → 세지 않음
    inbound = {"direction": "in", "origin": "peer", "claimed_at": None, "created_at": TODAY + timedelta(hours=3)}
    _call(session, **inbound, status="completed", duration_s=60)
    _call(session, **inbound, status="in_call", duration_s=None)
    _call(session, **inbound, status="rejected")
    _call(session, **inbound, status="rejected")
    _call(session, **inbound, status="missed")
    _call(session, **{**inbound, "created_at": TODAY - timedelta(hours=1)}, status="rejected")  # 어제(서울)
    session.commit()

    got = outreach_usage.summary(session, days=1, now=NOW)
    assert got.calls_placed == 3 == outreach.sent_count(session, "call", NOW.date())
    assert (got.calls_answered, got.calls_rejected) == (2, 2)
    assert got.call_seconds == 95 + 60


def test_cost_is_none_when_nothing_reported_and_sum_when_reported(session):
    _message(session)
    _call(session, duration_s=10)
    outreach.add_usage(session, "draft", model="m", input_tokens=10, output_tokens=5)
    _usage_at_nine(session)
    session.commit()
    got = outreach_usage.summary(session, days=1, now=NOW)
    assert got.provider_cost is None and got.by_kind["draft"].cost is None  # 알려 주지 않으면 계산해 채우지 않는다

    _message(session, provider_cost=0.0)
    _call(session, provider_cost=1.25)
    _message(session, provider_cost=9.0, claimed_at=TODAY - timedelta(days=3))  # 창 밖
    outreach.add_usage(session, "draft", model="m", cost=0.5)
    outreach.add_usage(session, "draft", model="m", cost=0.25)
    _usage_at_nine(session)
    session.commit()
    got = outreach_usage.summary(session, days=1, now=NOW)
    assert got.provider_cost == pytest.approx(1.25)
    assert got.by_kind["draft"].cost == pytest.approx(0.75)


def test_by_kind_tokens(session):
    outreach.add_usage(session, "text_reply", ref=("message", 1), model="m", input_tokens=100, output_tokens=20)
    outreach.add_usage(session, "text_reply", model="m", input_tokens=50, output_tokens=10)
    outreach.add_usage(session, "voice_model", ref=("call", 1), model="v", seconds=95)
    outreach.add_usage(session, "transcription", model="t", seconds=None)
    _usage_at_nine(session)
    session.add(OutreachUsage(kind="summary", at=TODAY - timedelta(seconds=1), input_tokens=999))
    session.commit()

    got = outreach_usage.summary(session, days=1, now=NOW)
    assert got.by_kind == {
        "text_reply": KindUsage(count=2, input_tokens=150, output_tokens=30, seconds=0, cost=None),
        "transcription": KindUsage(count=1, input_tokens=0, output_tokens=0, seconds=0, cost=None),
        "voice_model": KindUsage(count=1, input_tokens=0, output_tokens=0, seconds=95, cost=None),
    }
    assert outreach_usage.summary(session, days=2, now=NOW).by_kind["summary"].input_tokens == 999
    assert asdict(got)["by_kind"]["text_reply"]["input_tokens"] == 150  # API 가 그대로 내보낼 수 있다


def test_now_defaults_to_the_current_seoul_day(session):
    _message(session, claimed_at=datetime.now(UTC))
    session.commit()
    assert outreach_usage.summary(session, days=1).sms == 1
