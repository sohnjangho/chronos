"""계획 4 표와 저장소(Task 61): 새 표 12개, 기존 DB 올리기, 일정(프로젝트) 격리, 차지하기·셈, 알림 연결 한도.

번호·이름은 모두 가상이다(이름표의 010-0000-0199 = 정리한 꼴 01000000199).
"""

import logging
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import DateTime, create_engine, insert, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.core.model import CalendarSpec
from app.db import close_db, init_db
from app.store import contacts, outreach
from app.store.contacts import NotFound
from app.store.outreach import LIMIT_RANGES, Limits, limits, validate_limits
from app.store.tables import Base
from app.store.tables_outreach import (
    BlockedNumber,
    Contact,
    ContactCompany,
    ContactProposal,
    ContactReport,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
    OutreachUsage,
    UtcDateTime,
    VoiceSettings,
)
from app.store.upgrade import add_missing_columns
from tests import schedules

NEW_TABLES = {
    "contact_companies", "contacts", "contact_proposals", "outreach_messages", "outreach_calls", "contact_reports",
    "blocked_numbers", "do_not_contact_numbers", "outreach_usage", "notify_connections", "kakao_templates",
    "voice_settings",
}
PHONE = "01000000199"  # SENTINEL_PHONE 정리한 꼴
OTHER_PHONE = "01000000000"
KST = ZoneInfo("Asia/Seoul")
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
    """계획 3 모양 DB(새 표 없음) → init_db → 새 표 12개가 생기고 있던 줄은 그대로."""
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


def _raw(session: Session, sql: str):
    return session.connection().exec_driver_sql(sql).scalar()


def test_aware_times_are_stored_as_the_same_instant(session):
    """KST 시각과 같은 순간의 UTC 시각은 같은 값으로 저장되고 같은 순간으로 읽힌다(읽으면 시간대 없는 UTC)."""
    kst = _message(session, scheduled_at=datetime(2026, 11, 30, 8, 0, tzinfo=KST))
    utc = _message(session, scheduled_at=datetime(2026, 11, 29, 23, 0, tzinfo=UTC))
    session.commit()
    session.expire_all()
    stored = {_raw(session, f"SELECT scheduled_at FROM outreach_messages WHERE id = {row.id}") for row in (kst, utc)}
    assert stored == {"2026-11-29 23:00:00.000000"}
    assert session.get(OutreachMessage, kst.id).scheduled_at == session.get(OutreachMessage, utc.id).scheduled_at
    assert session.get(OutreachMessage, kst.id).scheduled_at == datetime(2026, 11, 29, 23, 0)  # app.store.timeutil 규칙


def test_naive_time_is_taken_as_utc(session):
    row = _call(session, scheduled_at=datetime(2026, 11, 29, 23, 0))
    session.commit()
    session.expire_all()
    assert _raw(session, f"SELECT scheduled_at FROM outreach_calls WHERE id = {row.id}") == "2026-11-29 23:00:00.000000"
    assert session.get(OutreachCall, row.id).scheduled_at == datetime(2026, 11, 29, 23, 0)


def test_every_outreach_time_column_stores_utc():
    tables = [t for t in Base.metadata.sorted_tables if t.name in NEW_TABLES]
    times = [c for t in tables for c in t.columns if isinstance(c.type, (DateTime, UtcDateTime))]
    assert len(times) > 20
    assert [f"{c.table.name}.{c.name}" for c in times if not isinstance(c.type, UtcDateTime)] == []


# ── 격리 ────────────────────────────────────────────────────────────


def _project_rows(session: Session, schedule_id: int) -> dict[str, int]:
    company = _company(session, schedule_id)
    person = _person(session, company, "김공정", phone=PHONE)
    message = _message(session, schedule_id=schedule_id, contact_id=person.id)
    call = _call(session, schedule_id=schedule_id, contact_id=person.id)
    session.add(ContactProposal(schedule_id=schedule_id, kind="new", name="박새사람"))
    outreach.add_report(session, schedule_id=schedule_id, medium="sms", kind="delay", text="늦습니다")
    session.flush()
    return {"company": company.id, "person": person.id, "message": message.id, "call": call.id}


def _counts(session: Session, schedule_id: int | None) -> list[int]:
    models = (ContactCompany, Contact, ContactProposal, OutreachMessage, OutreachCall, ContactReport)
    where = (lambda m: m.schedule_id.is_(None)) if schedule_id is None else (lambda m: m.schedule_id == schedule_id)
    return [len(list(session.scalars(select(m).where(where(m))))) for m in models]


def test_purge_schedule_removes_only_that_schedules_rows(session, sid, sid2):
    _project_rows(session, sid)
    _project_rows(session, sid2)
    _message(session, direction="in", status="received", origin="peer", peer_number=PHONE)
    _call(session, direction="in", status="missed", origin="peer", peer_number=PHONE)
    session.add(ContactProposal(kind="new", name="모르는 분"))
    outreach.add_report(session, medium="call", kind="message", text="전화 주세요")
    outreach.add_usage(session, "text_reply", ref=("message", 1))
    session.commit()

    outreach.purge_schedule(session, sid2)
    session.commit()

    assert _counts(session, sid2) == [0, 0, 0, 0, 0, 0]
    assert _counts(session, sid) == [1, 1, 1, 1, 1, 1]
    assert _counts(session, None) == [0, 0, 1, 1, 1, 1]  # 일정 없는 줄은 남는다
    assert len(list(session.scalars(select(OutreachUsage)))) == 1


# ── 수신 거부는 번호 기준(PM 11-23) ─────────────────────────────────


def test_do_not_contact_survives_schedule_deletion(session, sid, sid2):
    _person(session, _company(session, sid2), "김공정", phone=PHONE, do_not_contact=True, dnc_reason="문자 그만")
    session.commit()
    outreach.purge_schedule(session, sid2)
    session.commit()
    assert contacts.by_number(session, PHONE) == []
    assert outreach.is_do_not_contact(session, PHONE) is True


def test_do_not_contact_follows_the_number_into_other_schedules(session, sid, sid2):
    _person(session, _company(session, sid), "김공정", phone=PHONE)  # 이 일정에는 표시가 없다
    _person(session, _company(session, sid2), "김공정", phone=PHONE, do_not_contact=True, hidden=True)
    _person(session, _company(session, sid), "이반장", phone=OTHER_PHONE)
    assert outreach.is_do_not_contact(session, "010-0000-0199") is True  # 번호는 정리해서 본다
    assert outreach.is_do_not_contact(session, OTHER_PHONE) is False
    outreach.mark_do_not_contact(session, OTHER_PHONE, reason="전화로 요청")  # 연락처 줄과 상관없이 번호에
    outreach.mark_do_not_contact(session, "010-0000-0000", reason="두 번째")  # 이미 있으면 그대로
    assert outreach.is_do_not_contact(session, OTHER_PHONE) is True
    assert outreach.is_do_not_contact(session, "번호 아님") is False


def test_clear_do_not_contact_removes_it_everywhere(session, sid, sid2):
    here = _person(session, _company(session, sid), "김공정", phone=PHONE, do_not_contact=True, dnc_reason="요청")
    there = _person(session, _company(session, sid2), "김공정", phone=PHONE, do_not_contact=True)
    outreach.mark_do_not_contact(session, PHONE, reason="요청")
    session.commit()
    outreach.clear_do_not_contact(session, "010-0000-0199")
    session.commit()
    session.expire_all()
    assert outreach.is_do_not_contact(session, PHONE) is False
    assert (here.do_not_contact, here.dnc_reason, there.do_not_contact) == (False, None, False)


def test_admin_block_is_not_do_not_contact(session):
    session.add(BlockedNumber(number=PHONE, reason="광고 전화", created_by="관리자"))
    session.flush()
    assert outreach.is_do_not_contact(session, PHONE) is False


def test_mark_do_not_contact_refuses_a_bad_number_without_echoing_it(session):
    with pytest.raises(ValueError) as err:
        outreach.mark_do_not_contact(session, "010-12-3456", reason="")
    assert "3456" not in str(err.value)


AUTOINCREMENT_TABLES = {  # id 가 FK 없이 다른 곳에 적히는 표 — 지운 뒤 같은 id 를 다시 쓰지 않는다
    "contact_companies", "contacts", "outreach_messages", "outreach_calls", "notify_connections", "kakao_templates",
}


def test_ids_are_not_reused_after_a_purge(session, sid, sid2):
    company = _company(session, sid2)
    person = _person(session, company, "김공정")
    message = _message(session, schedule_id=sid2, contact_id=person.id)
    call = _call(session, schedule_id=sid2, contact_id=person.id)
    old = [company.id, person.id, message.id, call.id]
    session.commit()
    outreach.purge_schedule(session, sid2)
    session.commit()

    company = _company(session, sid)
    person = _person(session, company, "이반장")
    new = [company.id, person.id, _message(session, schedule_id=sid).id, _call(session, schedule_id=sid).id]
    assert all(n > o for n, o in zip(new, old, strict=True))


def test_autoincrement_tables_and_upgrade_is_unaffected(session):
    engine = session.get_bind()
    with engine.connect() as conn:
        sql = dict(conn.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type = 'table'").all())
    assert {name for name in NEW_TABLES if "AUTOINCREMENT" in sql[name]} == AUTOINCREMENT_TABLES
    assert add_missing_columns(engine, Base.metadata) == []  # 칸 더하기는 그대로(더할 것 없음)


def test_claim_never_moves_a_failed_row_back_out(session):
    """실패한 줄을 다시 차지하지 않는다 — 다시 보내기는 새 줄로(claimed_at 이 옮겨 가 그날 셈에서 빠지지 않게)."""
    first = datetime(2026, 11, 24, 1, 0, tzinfo=UTC)
    message = _message(session, status="failed", claimed_at=first)
    call = _call(session, status="failed", claimed_at=first)
    session.commit()
    assert outreach.claim(session, "message", message.id, ("draft", "failed"), "sending") is False
    assert outreach.claim(session, "call", call.id, ("failed",), "queued") is False
    assert outreach.claim(session, "message", message.id, ("failed",), "draft") is True  # 나가는 상태가 아니면 그대로
    session.commit()
    session.expire_all()
    assert session.get(OutreachCall, call.id).claimed_at == datetime(2026, 11, 24, 1, 0)


def test_unknown_messages_and_calls_are_rows_without_a_schedule(session, sid):
    _project_rows(session, sid)
    messages = [_message(session, direction="in", status="received", origin="peer", peer_number=PHONE,
                         body=f"글 {i}") for i in range(4)]
    calls = [_call(session, direction="in", status="missed", origin="peer", peer_number=PHONE) for _ in range(3)]
    newest_first = messages[::-1]
    assert outreach.unknown_messages(session, limit=10) == newest_first
    assert outreach.unknown_messages(session, limit=2) == newest_first[:2]
    assert outreach.unknown_messages(session, limit=2, before=messages[2].id) == newest_first[2:]
    assert outreach.unknown_calls(session, limit=10) == calls[::-1]
    assert outreach.unknown_calls(session, limit=1, before=calls[1].id) == [calls[0]]


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


def test_missing_message_or_call_is_not_found(session, sid):
    with pytest.raises(NotFound):
        outreach.get_message(session, sid, 9999)
    with pytest.raises(NotFound):
        outreach.get_call(session, sid, 9999)


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


def test_by_number_normalizes_input_and_bad_input_finds_nobody(session, sid):
    here = _person(session, _company(session, sid), "김공정", phone=PHONE)
    assert contacts.by_number(session, "010-0000-0199") == [here]
    assert contacts.by_number(session, "+82 10-0000-0199") == [here]
    assert contacts.by_number(session, "메모: 010-0000-0199") == []  # 정리되지 않는 값은 빈 결과(오류 아님)


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


def test_losing_claim_does_not_leave_a_stale_status_in_memory(session):
    """진 쪽이 미리 읽어 둔 줄도 DB 의 참값을 보인다(진 claim 이 메모리의 상태를 바꾸지 않는다)."""
    row = _message(session, status="scheduled")
    session.commit()
    other = Session(session.get_bind())
    try:
        mine = other.get(OutreachMessage, row.id)
        assert mine.status == "scheduled"
        assert outreach.claim(session, "message", row.id, ("scheduled",), "sending") is True
        assert outreach.claim(session, "message", row.id, ("sending",), "accepted") is True
        session.commit()
        assert outreach.claim(other, "message", row.id, ("scheduled",), "sending") is False
        assert mine.status == "accepted"
    finally:
        other.close()


def test_claim_returns_false_when_the_database_is_locked(tmp_path):
    """다른 일꾼이 쓰기를 쥐고 있어 「database is locked」 이면 False(그쪽이 가졌다). 다른 DB 오류는 그대로 올린다."""
    engine = create_engine(f"sqlite:///{tmp_path / 'lock.db'}", connect_args={"timeout": 0.1})
    Base.metadata.create_all(engine, tables=[OutreachMessage.__table__])
    with Session(engine) as setup:
        setup.add(OutreachMessage(direction="out", channel="sms", origin="user", status="scheduled"))
        setup.add(OutreachMessage(direction="out", channel="sms", origin="user", status="scheduled"))
        setup.commit()
    holder, late = Session(engine), Session(engine)
    try:
        assert outreach.claim(holder, "message", 1, ("scheduled",), "sending") is True  # 쓰기 잠금을 쥔 채 commit 전
        assert outreach.claim(late, "message", 2, ("scheduled",), "sending") is False
        holder.commit()  # late 는 claim 이 되돌려 두어 그대로 다시 쓸 수 있다
        assert outreach.claim(late, "message", 2, ("scheduled",), "sending") is True
        late.commit()
    finally:
        holder.close()
        late.close()
    with Session(create_engine(f"sqlite:///{tmp_path / 'empty.db'}")) as broken, pytest.raises(OperationalError):
        outreach.claim(broken, "message", 1, ("scheduled",), "sending")  # 표가 없음 — 잠금이 아니면 숨기지 않는다


def test_claim_stamps_claimed_at_when_a_row_starts_to_leave(session):
    t1 = datetime(2026, 11, 24, 1, 0, tzinfo=UTC)
    t2 = datetime(2026, 11, 24, 1, 5, tzinfo=UTC)
    message = _message(session, status="scheduled")
    call = _call(session, status="scheduled")
    session.commit()
    assert outreach.claim(session, "message", message.id, ("draft", "scheduled"), "sending", now=t1)
    assert outreach.claim(session, "call", call.id, ("draft", "scheduled"), "queued", now=t1)
    assert outreach.claim(session, "call", call.id, ("queued",), "dialing", now=t2)  # 이미 나가는 중 — 그대로
    assert outreach.claim(session, "message", message.id, ("sending",), "accepted", now=t2)
    session.commit()
    session.expire_all()
    assert session.get(OutreachMessage, message.id).claimed_at == datetime(2026, 11, 24, 1, 0)
    assert session.get(OutreachCall, call.id).claimed_at == datetime(2026, 11, 24, 1, 0)
    blocked = _call(session, status="draft")
    session.commit()
    assert outreach.claim(session, "call", blocked.id, ("draft",), "blocked_hours", now=t2)
    session.commit()
    session.expire_all()
    assert session.get(OutreachCall, blocked.id).claimed_at is None  # 나가기 전에 막힌 것은 찍지 않는다


def test_sent_count_uses_kst_day(session):
    utc_1530 = datetime(2026, 11, 23, 15, 30, tzinfo=UTC)  # 서울 11-24 00:30
    _message(session, status="accepted", peer_number=PHONE, claimed_at=utc_1530)
    assert outreach.sent_count(session, "sms", date(2026, 11, 24)) == 1
    assert outreach.sent_count(session, "sms", date(2026, 11, 23)) == 0


def test_sent_count_puts_a_kst_2330_send_on_that_kst_day(session):
    _message(session, status="accepted", peer_number=PHONE, claimed_at=datetime(2026, 11, 24, 23, 30, tzinfo=KST))
    assert [outreach.sent_count(session, "sms", date(2026, 11, d)) for d in (23, 24, 25)] == [0, 1, 0]


def test_sent_count_counts_claimed_rows_by_claim_time(session, sid):
    """나가려고 차지한(claimed_at 이 있는) 것은 그 뒤 실패해도 센다. 나가기 전에 막힌 것은 세지 않는다."""
    day = date(2026, 11, 24)
    at = datetime(2026, 11, 24, 1, 0, tzinfo=UTC)
    person = _person(session, _company(session, sid), "김공정", phone=PHONE)
    for status in ("sending", "accepted", "delivered", "unconfirmed", "failed"):
        _message(session, schedule_id=sid, contact_id=person.id, status=status, claimed_at=at)
    for status in ("draft", "scheduled", "blocked_test"):
        _message(session, schedule_id=sid, contact_id=person.id, status=status, sent_at=at, created_at=at)
    _message(session, status="accepted", peer_number=PHONE, claimed_at=at - timedelta(days=1))  # 전날
    _message(session, direction="in", status="received", peer_number=PHONE, claimed_at=at)
    _message(session, channel="kakao", status="accepted", peer_number=PHONE, claimed_at=at)
    _message(session, channel="kakao", status="delivered", peer_number=PHONE, claimed_at=at, fallback_sms=True)
    _message(session, status="accepted", peer_number=OTHER_PHONE, claimed_at=at)

    assert outreach.sent_count(session, "sms", day) == 7  # 문자 5 + 문자로 대신 나간 카카오톡 1 + 다른 번호 1
    assert outreach.sent_count(session, "sms", day, number=PHONE) == 6  # 연락처 번호로 간 것 + peer_number
    assert outreach.sent_count(session, "sms", day, number="010-0000-0199") == 6  # 번호는 정리해서 본다
    assert outreach.sent_count(session, "sms", day, number="번호 아님") == 0
    assert outreach.sent_count(session, "sms", day, number=OTHER_PHONE) == 1
    assert outreach.sent_count(session, "kakao", day, number=PHONE) == 1


def test_sent_count_of_calls_by_number_is_exact(session, sid):
    day = date(2026, 11, 24)
    at = datetime(2026, 11, 24, 1, 0, tzinfo=UTC)
    person = _person(session, _company(session, sid), "김공정", phone=PHONE)
    other = _person(session, _company(session, sid), "이반장", phone=OTHER_PHONE)
    for status in ("queued", "dialing", "in_call", "completed", "no_answer", "busy", "failed"):
        _call(session, schedule_id=sid, contact_id=person.id, status=status, claimed_at=at)
    for status in ("draft", "scheduled", "blocked_test", "blocked_hours"):
        _call(session, schedule_id=sid, contact_id=person.id, status=status, created_at=at)
    _call(session, direction="in", status="completed", peer_number=PHONE, claimed_at=at)
    _call(session, schedule_id=sid, contact_id=other.id, status="completed", claimed_at=at)
    _call(session, status="no_answer", peer_number=PHONE, claimed_at=at)  # 주소록 밖 번호로 건 것
    assert outreach.sent_count(session, "call", day) == 9
    assert outreach.sent_count(session, "call", day, number=PHONE) == 8
    assert outreach.sent_count(session, "call", day, number=OTHER_PHONE) == 1
    assert outreach.sent_count(session, "call", day + timedelta(days=1), number=PHONE) == 0


def test_auto_replies_are_claimed_ones_to_that_number(session):
    since = datetime(2026, 11, 24, 0, 0, tzinfo=UTC)
    hour = timedelta(hours=1)
    first = _message(session, kind="auto_reply", status="accepted", peer_number=PHONE, claimed_at=since + hour)
    notice = _message(session, kind="notice", status="failed", peer_number=PHONE, claimed_at=since + 2 * hour)
    _message(session, kind="auto_reply", status="accepted", peer_number=PHONE, claimed_at=since - hour)
    _message(session, kind="auto_reply", status="draft", peer_number=PHONE)
    _message(session, kind="normal", status="accepted", peer_number=PHONE, claimed_at=since + hour)
    _message(session, kind="auto_reply", status="accepted", peer_number=OTHER_PHONE, claimed_at=since)
    assert outreach.auto_replies(session, PHONE, since) == [first, notice]
    assert outreach.auto_replies(session, "010-0000-0199", since) == [first, notice]
    assert outreach.auto_replies(session, "번호 아님", since) == []


def test_live_call(session, sid):
    person = _person(session, _company(session, sid), "김공정")
    _call(session, schedule_id=sid, contact_id=person.id, status="completed")
    assert outreach.live_call(session, person.id) is False
    for status in ("queued", "dialing", "in_call"):
        row = _call(session, schedule_id=sid, contact_id=person.id, status=status)
        assert outreach.live_call(session, person.id) is True
        row.status = "completed"
        session.flush()


def test_live_call_of_one_contact_does_not_make_another_live(session, sid):
    company = _company(session, sid)
    kim = _person(session, company, "김공정")
    lee = _person(session, company, "이반장")
    _call(session, schedule_id=sid, contact_id=kim.id, status="in_call")
    assert outreach.live_call(session, kim.id) is True
    assert outreach.live_call(session, lee.id) is False


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


@pytest.fixture
def fresh_warnings(monkeypatch):
    """한도 경고는 칸마다 프로세스에 한 번 — 시험마다 새로 센다."""
    monkeypatch.setattr(outreach, "_warned", set())


def test_limits_defaults_when_nothing_stored():
    assert limits(None) == limits(_conn(None)) == limits(_conn({})) == Limits()
    assert vars(Limits()) == DEFAULTS
    assert set(LIMIT_RANGES) == set(DEFAULTS)


def test_limits_partial_override():
    got = limits(_conn({"per_contact_sms_daily": 3, "max_call_seconds": 600}))
    assert vars(got) == {**DEFAULTS, "per_contact_sms_daily": 3, "max_call_seconds": 600}


@pytest.mark.parametrize("key,value", [
    ("daily_sms_total", -1), ("daily_sms_total", 10_001), ("daily_calls_total", 10_001),
    ("max_call_seconds", 7_201), ("max_call_seconds", 29), ("max_call_seconds_unknown", 7_201),
    ("inbound_burst_count", 0),
    ("auto_reply_hourly", "5"), ("auto_reply_daily", 2.5), ("inbound_burst_count", True), ("reply_grace_minutes", None),
])
def test_limits_invalid_value_falls_back_to_default(key, value, caplog, fresh_warnings):
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


def test_limits_warns_once_per_field(caplog, fresh_warnings):
    caplog.set_level(logging.WARNING, logger="app.store.outreach")
    for _ in range(3):
        limits(_conn({"daily_sms_total": -1}))
    limits(_conn({"daily_calls_total": -1}))
    assert len(caplog.records) == 2


def test_limits_keep_unknown_callers_no_longer_than_max_call(fresh_warnings):
    assert limits(_conn({"max_call_seconds": 60})).max_call_seconds_unknown == 60  # 기본 120 → 60
    got = limits(_conn({"max_call_seconds": 90, "max_call_seconds_unknown": 600}))
    assert (got.max_call_seconds, got.max_call_seconds_unknown) == (90, 90)


def test_validate_limits_accepts_good_values():
    assert validate_limits({}) == {}
    assert validate_limits(DEFAULTS) == {}
    assert validate_limits({"daily_sms_total": 10_000, "max_call_seconds": 30, "max_call_seconds_unknown": 30}) == {}


def test_validate_limits_checks_each_field():
    errors = validate_limits({"nope": 1, "daily_sms_total": -1, "daily_calls_total": "3", "auto_reply_daily": True,
                              "max_call_seconds": 7_201, "inbound_burst_count": 0})
    assert set(errors) == {"nope", "daily_sms_total", "daily_calls_total", "auto_reply_daily", "max_call_seconds",
                           "inbound_burst_count"}
    assert errors["nope"] == "알 수 없는 한도입니다."
    assert errors["daily_calls_total"] == errors["auto_reply_daily"] == "정수로 넣어 주세요."
    assert errors["daily_sms_total"] == "0~10,000 사이로 넣어 주세요."
    assert errors["max_call_seconds"] == "30~7,200 사이로 넣어 주세요."
    assert errors["inbound_burst_count"] == "1~10,000 사이로 넣어 주세요."
    assert validate_limits({"max_call_seconds": 29}) == {"max_call_seconds": "30~7,200 사이로 넣어 주세요."}


@pytest.mark.parametrize("values,field", [
    ({"max_call_seconds": 60, "max_call_seconds_unknown": 61}, "max_call_seconds_unknown"),
    ({"max_call_seconds": 60}, "max_call_seconds_unknown"),  # 빠진 칸은 기본값(120)으로 견준다
    ({"auto_reply_hourly": 21}, "auto_reply_hourly"),
    ({"auto_reply_hourly": 3, "auto_reply_daily": 2}, "auto_reply_hourly"),
    ({"per_contact_sms_daily": 51}, "per_contact_sms_daily"),
    ({"per_contact_sms_daily": 5, "daily_sms_total": 4}, "per_contact_sms_daily"),
    ({"per_contact_calls_daily": 11}, "per_contact_calls_daily"),
    ({"per_contact_calls_daily": 2, "daily_calls_total": 1}, "per_contact_calls_daily"),
])
def test_validate_limits_checks_pairs(values, field):
    errors = validate_limits(values)
    assert list(errors) == [field] and errors[field]


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
