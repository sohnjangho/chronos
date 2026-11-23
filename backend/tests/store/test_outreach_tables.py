"""계획 4 표와 저장소(Task 61): 새 표 11개, 기존 DB 올리기, 일정(프로젝트) 격리, 차지하기·셈, 알림 연결 한도.

번호·이름은 모두 가상이다(이름표의 010-0000-0199 = 정리한 꼴 01000000199).
"""

import logging
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.core.model import CalendarSpec
from app.db import close_db, init_db
from app.store import contacts, outreach
from app.store.contacts import NotFound
from app.store.outreach import LIMIT_RANGES, Limits, limits
from app.store.tables import Base
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    ContactReport,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
    OutreachUsage,
    VoiceSettings,
)
from tests import schedules

NEW_TABLES = {
    "contact_companies", "contacts", "contact_proposals", "outreach_messages", "outreach_calls", "contact_reports",
    "blocked_numbers", "outreach_usage", "notify_connections", "kakao_templates", "voice_settings",
}
PHONE = "01000000199"  # SENTINEL_PHONE 정리한 꼴
OTHER_PHONE = "01000000000"
BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def sid2(session) -> int:
    """sid 를 본뜬 둘째 일정. 달력이 sid(주 5일)와 다르다: 주 6일, 2027-03-01 공휴일."""
    cal = CalendarSpec(days_per_week=6, holidays=(date(2027, 3, 1),))
    return schedules.store(session, schedules.make([schedules.task("A", 3)], cal=cal))


def _company(session: Session, schedule_id: int, name: str = "가나건설", **kw) -> ContactCompany:
    row = ContactCompany(schedule_id=schedule_id, name=name, **kw)
    session.add(row)
    session.flush()
    return row


def _person(session: Session, company: ContactCompany, name: str, **kw) -> Contact:
    row = Contact(schedule_id=company.schedule_id, company_id=company.id, name=name, **kw)
    session.add(row)
    session.flush()
    return row


def _message(session: Session, **kw) -> OutreachMessage:
    row = OutreachMessage(**{"direction": "out", "channel": "sms", "origin": "user", "body": "내일 타설 가능하신가요",
                             "status": "draft", **kw})
    session.add(row)
    session.flush()
    return row


def _call(session: Session, **kw) -> OutreachCall:
    row = OutreachCall(**{"origin": "user", "purpose": "타설 일정 확인", "status": "draft", **kw})
    session.add(row)
    session.flush()
    return row


def _tables(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as db:
        return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


# ── 표 ──────────────────────────────────────────────────────────────


def test_existing_db_gets_new_tables(tmp_path):
    """계획 3 모양 DB(새 표 없음) → init_db → 새 표 11개가 생기고 있던 줄은 그대로."""
    path = tmp_path / "data" / "chronos.db"  # 시험 환경의 CHRONOS_DATA_DIR(tests/conftest.py)
    path.parent.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in NEW_TABLES])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO schedules (id, name, domain, level, current_version, created_by, created_at, "
                          "weight_mode) VALUES (1, '5층 사무동 신축', 'construction', 'L3', 1, '김하늘', "
                          "'2026-11-20 09:00:00', 'duration')"))
    engine.dispose()
    assert not NEW_TABLES & _tables(path)

    init_db()
    close_db()

    assert NEW_TABLES <= _tables(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT id, name, created_by FROM schedules").fetchall() == [(1, "5층 사무동 신축", "김하늘")]


def test_app_db_registers_outreach_tables():
    """app.db 만 import 해도(서버가 뜰 때처럼) 새 표가 Base 에 올라 있다 — init_db 의 create_all 이 만든다."""
    code = ("import app.db; from app.store.tables import Base; "
            "print(','.join(sorted(Base.metadata.tables)))")
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, check=True)
    assert NEW_TABLES <= set(out.stdout.strip().split(","))


def test_defaults(session):
    conn = NotifyConnection(name="한국AI통신", base_url="https://api.example.invalid", secret_ciphertext="x",
                            secret_last4="9999", account_id="acc")
    company = _company(session, 1)
    person = _person(session, company, "김공정")
    session.add(conn)
    session.flush()
    assert conn.test_mode and conn.agent_sms == "approve" and conn.inbound_mode == "off"
    assert (conn.agent_kakao, conn.agent_call, conn.provider, conn.is_default) == ("approve", "approve", "koreaaitel",
                                                                                   False)
    assert conn.limits_json is None and conn.allow_numbers_json == []
    assert (person.can_sms, person.can_kakao, person.can_call) == (True, True, True)
    assert (person.gender, person.language, person.voice_mode, person.do_not_contact, person.hidden) == (
        "unknown", "ko", "auto", False, False)
    message = _message(session)
    other = _message(session)
    assert message.kind == "normal" and message.checks == 0 and message.harness_json == []
    assert message.idempotency_key and message.idempotency_key != other.idempotency_key  # 메시지마다 고유 키
    call = _call(session)
    assert (call.direction, call.auto_retry_used, call.transcript_json) == ("out", False, [])


def test_message_without_contact_keeps_peer_number(session, sid):
    row = _message(session, direction="in", origin="peer", status="received", peer_number=PHONE,
                   caller_class="unknown", body="누구세요")
    session.commit()
    session.expire_all()
    stored = session.get(OutreachMessage, row.id)
    assert (stored.schedule_id, stored.contact_id, stored.peer_number) == (None, None, PHONE)
    with pytest.raises(NotFound):  # 어느 일정에도 들지 않은 줄은 일정으로 찾을 수 없다
        outreach.get_message(session, sid, row.id)


# ── 격리 ────────────────────────────────────────────────────────────


def test_get_contact_of_other_project_is_not_found(session, sid, sid2):
    company = _company(session, sid2)
    person = _person(session, company, "김공정", phone=PHONE)
    assert contacts.get_contact(session, sid2, person.id) is person
    assert contacts.get_company(session, sid2, company.id) is company
    with pytest.raises(NotFound):
        contacts.get_contact(session, sid, person.id)
    with pytest.raises(NotFound):
        contacts.get_company(session, sid, company.id)
    with pytest.raises(NotFound):
        contacts.get_contact(session, sid, 9999)


def test_messages_calls_and_thread_of_other_project_are_not_found(session, sid, sid2):
    company = _company(session, sid2)
    person = _person(session, company, "김공정", phone=PHONE)
    message = _message(session, schedule_id=sid2, contact_id=person.id)
    call = _call(session, schedule_id=sid2, contact_id=person.id)
    assert outreach.get_message(session, sid2, message.id) is message
    assert outreach.get_call(session, sid2, call.id) is call
    with pytest.raises(NotFound):
        outreach.get_message(session, sid, message.id)
    with pytest.raises(NotFound):
        outreach.get_call(session, sid, call.id)
    with pytest.raises(NotFound):
        outreach.thread(session, sid, person.id)


def test_search_stays_in_project_and_skips_hidden(session, sid, sid2):
    mine = _company(session, sid, "가나건설")
    hidden_company = _company(session, sid, "다라설비", hidden=True)
    theirs = _company(session, sid2, "가나건설")
    kim = _person(session, mine, "김공정", role_title="현장 소장")
    _person(session, mine, "김숨김", hidden=True)
    _person(session, hidden_company, "김설비")
    _person(session, theirs, "김공정")
    lee = _person(session, mine, "이반장", role_title="형틀 반장")
    other_mine = _company(session, sid, "마바전기")
    park = _person(session, other_mine, "박전기", role_title="반장")

    assert contacts.search(session, sid, "김") == [kim]
    assert contacts.search(session, sid, "반장") == [park, lee]  # 이름 순
    assert contacts.search(session, sid, "반장", company_ids=[mine.id]) == [lee]
    assert contacts.search(session, sid, "_") == []  # 찾는 말의 _·% 는 글자 그대로
    assert contacts.search(session, sid, "", limit=2) == contacts.search(session, sid, "")[:2]


def test_search_puts_exact_name_first(session, sid):
    company = _company(session, sid)
    _person(session, company, "김공정 대리")
    exact = _person(session, company, "김공정")
    assert contacts.search(session, sid, "김공정")[0] is exact


def test_listed_groups_by_company_and_hides_hidden(session, sid, sid2):
    a = _company(session, sid, "가나건설")
    b = _company(session, sid, "다라설비", hidden=True)
    _company(session, sid2, "남의 회사")
    kim = _person(session, a, "김공정")
    gone = _person(session, a, "김숨김", hidden=True)
    lee = _person(session, b, "이설비")

    assert contacts.listed(session, sid) == [(a, [kim])]
    assert contacts.listed(session, sid, include_hidden=True) == [(a, [kim, gone]), (b, [lee])]


def test_by_number_spans_projects_and_keeps_hidden(session, sid, sid2):
    """by_number 는 모든 일정(문·일꾼 전용). 숨긴 사람도 돌려준다 — 수신 거부가 번호를 따라가게."""
    here = _person(session, _company(session, sid), "김공정", phone=PHONE)
    there = _person(session, _company(session, sid2), "김공정", phone=PHONE, hidden=True, do_not_contact=True)
    _person(session, _company(session, sid), "이반장", phone=OTHER_PHONE)
    assert contacts.by_number(session, PHONE) == [here, there]
    assert contacts.by_number(session, "") == []


def test_by_name_is_exact_across_projects_without_hidden(session, sid, sid2):
    here = _person(session, _company(session, sid), "김공정")
    there = _person(session, _company(session, sid2), "김공정")
    _person(session, _company(session, sid), "김공정 대리")
    _person(session, _company(session, sid2), "김공정", hidden=True)
    _person(session, _company(session, sid2, hidden=True), "김공정")
    assert contacts.by_name(session, " 김공정 ") == [here, there]
    assert contacts.by_name(session, "") == []


def test_calendar_of_reads_current_version_or_default(session, sid, sid2):
    assert contacts.calendar_of(session, sid) == CalendarSpec(days_per_week=5)
    assert contacts.calendar_of(session, sid2) == CalendarSpec(days_per_week=6, holidays=(date(2027, 3, 1),))
    assert contacts.calendar_of(session, None) == CalendarSpec(days_per_week=5)
    assert contacts.calendar_of(session, 9999) == CalendarSpec(days_per_week=5)


def test_thread_is_scoped_ordered_and_paged(session, sid, sid2):
    company = _company(session, sid)
    kim = _person(session, company, "김공정")
    lee = _person(session, company, "이반장")
    rows = [_message(session, schedule_id=sid, contact_id=kim.id, body=f"글 {i}") for i in range(5)]
    _message(session, schedule_id=sid, contact_id=lee.id)
    _message(session, schedule_id=sid2, contact_id=kim.id)  # 다른 일정에 잘못 붙은 줄도 보이지 않는다
    assert outreach.thread(session, sid, kim.id) == rows
    assert outreach.thread(session, sid, kim.id, limit=2) == rows[3:]
    assert outreach.thread(session, sid, kim.id, before=rows[3].id, limit=2) == rows[1:3]


# ── 차지하기·셈 ─────────────────────────────────────────────────────


def test_claim_is_won_once(session):
    row = _message(session)
    session.commit()
    assert outreach.claim(session, "message", row.id, ("draft", "scheduled"), "sending") is True
    session.commit()
    assert outreach.claim(session, "message", row.id, ("draft", "scheduled"), "sending") is False
    call = _call(session, status="scheduled")
    session.commit()
    assert outreach.claim(session, "call", call.id, ("scheduled",), "queued") is True
    assert outreach.claim(session, "call", call.id, ("scheduled",), "queued") is False


def test_claim_from_two_sessions_is_won_once(session):
    row = _message(session, status="scheduled")
    session.commit()
    other = Session(session.get_bind())
    try:
        assert outreach.claim(session, "message", row.id, ("scheduled",), "sending") is True
        session.commit()
        assert outreach.claim(other, "message", row.id, ("scheduled",), "sending") is False
        other.commit()
    finally:
        other.close()
    session.expire_all()
    assert session.get(OutreachMessage, row.id).status == "sending"


def test_sent_count_uses_kst_day(session):
    utc_1530 = datetime(2026, 11, 23, 15, 30, tzinfo=UTC)  # 서울 11-24 00:30
    _message(session, status="accepted", peer_number=PHONE, sent_at=utc_1530)
    assert outreach.sent_count(session, "sms", date(2026, 11, 24)) == 1
    assert outreach.sent_count(session, "sms", date(2026, 11, 23)) == 0


def test_sent_count_counts_only_outgoing_states_by_channel_and_number(session, sid):
    day = date(2026, 11, 24)
    at = datetime(2026, 11, 24, 1, 0, tzinfo=UTC)
    person = _person(session, _company(session, sid), "김공정", phone=PHONE)
    for status in ("sending", "accepted", "delivered", "unconfirmed"):
        _message(session, schedule_id=sid, contact_id=person.id, status=status, sent_at=at)
    for status in ("draft", "scheduled", "failed", "blocked_test"):
        _message(session, schedule_id=sid, contact_id=person.id, status=status, sent_at=at)
    _message(session, direction="in", status="received", peer_number=PHONE, sent_at=at)
    _message(session, channel="kakao", status="accepted", peer_number=PHONE, sent_at=at)
    _message(session, status="accepted", peer_number=OTHER_PHONE, sent_at=at)
    _message(session, status="sending", peer_number=PHONE, created_at=at)  # 보낸 시각이 아직 없으면 만든 시각
    _message(session, status="unconfirmed", peer_number=OTHER_PHONE, scheduled_at=at,  # 예약 시각이 만든 시각보다 먼저
             created_at=at - timedelta(days=3))

    assert outreach.sent_count(session, "sms", day) == 7
    assert outreach.sent_count(session, "sms", day, number=PHONE) == 5  # 연락처 번호로 간 것 + peer_number
    assert outreach.sent_count(session, "sms", day, number=OTHER_PHONE) == 2
    assert outreach.sent_count(session, "kakao", day, number=PHONE) == 1

    for status in ("queued", "dialing", "in_call", "completed", "no_answer", "busy", "failed"):
        _call(session, schedule_id=sid, contact_id=person.id, status=status, started_at=at)
    for status in ("draft", "scheduled", "blocked_test", "blocked_hours"):
        _call(session, schedule_id=sid, contact_id=person.id, status=status, started_at=at)
    _call(session, direction="in", status="completed", peer_number=PHONE, started_at=at)
    assert outreach.sent_count(session, "call", day) == 7
    assert outreach.sent_count(session, "call", day, number=OTHER_PHONE) == 0


def test_auto_replies_are_sent_ones_to_that_number(session):
    since = datetime(2026, 11, 24, 0, 0, tzinfo=UTC)
    first = _message(session, kind="auto_reply", status="accepted", peer_number=PHONE, sent_at=since + timedelta(1 / 24))
    notice = _message(session, kind="notice", status="delivered", peer_number=PHONE, sent_at=since + timedelta(2 / 24))
    _message(session, kind="auto_reply", status="accepted", peer_number=PHONE, sent_at=since - timedelta(1 / 24))
    _message(session, kind="auto_reply", status="draft", peer_number=PHONE)
    _message(session, kind="normal", status="accepted", peer_number=PHONE, sent_at=since + timedelta(1 / 24))
    _message(session, kind="auto_reply", status="accepted", peer_number=OTHER_PHONE, sent_at=since)
    assert outreach.auto_replies(session, PHONE, since) == [first, notice]


def test_live_call(session, sid):
    person = _person(session, _company(session, sid), "김공정")
    _call(session, schedule_id=sid, contact_id=person.id, status="completed")
    assert outreach.live_call(session, person.id) is False
    for status in ("queued", "dialing", "in_call"):
        row = _call(session, schedule_id=sid, contact_id=person.id, status=status)
        assert outreach.live_call(session, person.id) is True
        row.status = "completed"
        session.flush()


def test_connection_is_the_default_one(session):
    assert outreach.connection(session) is None
    session.add(NotifyConnection(name="예비", base_url="https://a.invalid", secret_ciphertext="x", secret_last4="1111",
                                 account_id="a"))
    main = NotifyConnection(name="기본", base_url="https://b.invalid", secret_ciphertext="x", secret_last4="2222",
                            account_id="b", is_default=True)
    session.add(main)
    session.flush()
    assert outreach.connection(session) is main


def test_add_report_and_usage(session, sid):
    report = outreach.add_report(session, schedule_id=sid, medium="sms", message_id=7, kind="delay",
                                 text="자재가 하루 늦습니다", quote="하루 늦습니다", quote_found=True)
    outreach.add_usage(session, "text_reply", ref=("message", 7), model="m-1", input_tokens=10, output_tokens=5)
    outreach.add_usage(session, "voice_sample", seconds=4)
    session.commit()
    assert isinstance(report, ContactReport) and report.id and report.status == "open"
    usage = list(session.scalars(select(OutreachUsage).order_by(OutreachUsage.id)))
    assert [(u.kind, u.ref_kind, u.ref_id, u.input_tokens, u.seconds, u.cost) for u in usage] == [
        ("text_reply", "message", 7, 10, None, None), ("voice_sample", None, None, 0, 4, None)]
    assert all(u.at is not None for u in usage)


# ── 알림 연결 한도(PM 11-23: 설정·개발 콘솔에서 바꾼다 — 상수 아님) ──────


DEFAULTS = {
    "daily_sms_total": 50, "daily_calls_total": 10, "per_contact_sms_daily": 5, "per_contact_calls_daily": 2,
    "max_call_seconds": 300, "max_call_seconds_unknown": 120, "auto_reply_hourly": 5, "auto_reply_daily": 20,
    "inbound_burst_count": 5, "inbound_burst_minutes": 10, "reply_grace_minutes": 30, "unknown_notice_daily": 1,
}


def _conn(limits_json) -> NotifyConnection:
    return NotifyConnection(name="기본", base_url="https://b.invalid", secret_ciphertext="x", secret_last4="2222",
                            account_id="b", limits_json=limits_json)


def test_limits_defaults_when_nothing_stored():
    assert limits(None) == limits(_conn(None)) == limits(_conn({})) == Limits()
    assert vars(Limits()) == DEFAULTS
    assert set(LIMIT_RANGES) == set(DEFAULTS)


def test_limits_partial_override():
    got = limits(_conn({"per_contact_sms_daily": 3, "max_call_seconds": 600}))
    assert vars(got) == {**DEFAULTS, "per_contact_sms_daily": 3, "max_call_seconds": 600}


@pytest.mark.parametrize("key,value", [
    ("daily_sms_total", -1), ("daily_sms_total", 10_001), ("daily_calls_total", 10_001),
    ("max_call_seconds", 7_201), ("max_call_seconds", 0), ("max_call_seconds_unknown", 7_201),
    ("auto_reply_hourly", "5"), ("auto_reply_daily", 2.5), ("inbound_burst_count", True), ("reply_grace_minutes", None),
])
def test_limits_invalid_value_falls_back_to_default(key, value, caplog):
    caplog.set_level(logging.WARNING, logger="app.store.outreach")
    got = limits(_conn({key: value, "per_contact_calls_daily": 1}))
    assert vars(got) == {**DEFAULTS, "per_contact_calls_daily": 1}
    logged = [r.getMessage() for r in caplog.records]
    assert len(logged) == 1 and key in logged[0] and str(value) not in logged[0].replace(key, "")  # 칸 이름만


def test_limits_edges_are_allowed():
    got = limits(_conn({"daily_sms_total": 10_000, "daily_calls_total": 0, "max_call_seconds": 7_200,
                        "reply_grace_minutes": 0}))
    assert (got.daily_sms_total, got.daily_calls_total, got.max_call_seconds, got.reply_grace_minutes) == (
        10_000, 0, 7_200, 0)


def test_limits_non_object_and_unknown_keys_fall_back():
    assert limits(_conn([1, 2])) == Limits()
    assert limits(_conn({"not_a_limit": 3})) == Limits()


def test_old_connection_row_without_limits_column_upgrades(tmp_path):
    """limits_json 이 없던 notify_connections(줄 하나) → init_db → 칸이 더해지고 줄은 그대로, 한도는 기본값."""
    path = tmp_path / "data" / "chronos.db"
    path.parent.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{path}")
    ddl = str(CreateTable(NotifyConnection.__table__).compile(dialect=engine.dialect))
    old_ddl = "\n".join(line for line in ddl.splitlines() if "limits_json" not in line)
    with engine.begin() as conn:
        conn.exec_driver_sql(old_ddl)
        conn.execute(insert(NotifyConnection.__table__).values(
            id=1, name="기본", base_url="https://b.invalid", secret_ciphertext="x", secret_last4="2222",
            account_id="b", test_mode=False, agent_sms="delegate", is_default=True))
    engine.dispose()

    init_db()
    close_db()

    with closing(sqlite3.connect(path)) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(notify_connections)")]
        row = db.execute("SELECT name, test_mode, agent_sms, limits_json FROM notify_connections").fetchone()
    assert columns[-1] == "limits_json"
    assert row == ("기본", 0, "delegate", None)
    with Session(create_engine(f"sqlite:///{path}")) as session:
        conn = outreach.connection(session)
        assert conn.name == "기본" and limits(conn) == Limits()


def test_limits_live_only_in_limits_json():
    """한도는 한 곳(limits_json → limits)에만 둔다 — 알림 연결·음성 설정 줄에 따로 칸을 두지 않는다."""
    assert "max_call_seconds" not in VoiceSettings.__table__.c
    assert not {"daily_sms_limit", "daily_call_limit", "person_sms_limit", "person_call_limit"} & set(
        NotifyConnection.__table__.c.keys())
