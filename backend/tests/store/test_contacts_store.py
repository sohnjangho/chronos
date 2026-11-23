"""주소록 API(Task 72 고침 1차)가 쓰는 저장소: 번호 보기 기록 표(contact_reveals)·셈, 여러 번호의 수신 거부를 한 번에
(do_not_contact_numbers), 같은 번호를 두 요청이 동시에 수신 거부할 때(mark_do_not_contact). 번호는 모두 가상이다."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from app.db import close_db, init_db
from app.outreach.phone import normalize
from app.store import outreach
from app.store.tables import Base
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    ContactReveal,
    DoNotContactNumber,
)
from tests import schedules

PHONE = "01000000199"  # SENTINEL_PHONE 정리한 꼴


def _person(session: Session, schedule_id: int, name: str, **kw) -> Contact:
    company = ContactCompany(schedule_id=schedule_id, name="가나건설")
    session.add(company)
    session.flush()
    row = Contact(schedule_id=schedule_id, company_id=company.id, name=name, **kw)
    session.add(row)
    session.flush()
    return row


def _tables(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as db:
        return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_existing_db_gets_the_reveal_table(tmp_path):
    """번호 보기 표가 없던 DB → init_db → 표가 생기고 있던 줄은 그대로."""
    path = tmp_path / "data" / "chronos.db"  # 시험 환경의 CHRONOS_DATA_DIR(tests/conftest.py)
    path.parent.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name != "contact_reveals"])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO do_not_contact_numbers (number, reason, created_at) "
                          "VALUES ('01000000199', '요청', '2026-11-20 09:00:00')"))
    engine.dispose()
    assert "contact_reveals" not in _tables(path)

    init_db()
    close_db()

    assert "contact_reveals" in _tables(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT number FROM do_not_contact_numbers").fetchall() == [(PHONE,)]
        assert "AUTOINCREMENT" in db.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'contact_reveals'").fetchone()[0].upper()


def test_reveals_are_counted_per_user_since_a_time_and_outlive_the_schedule(session, sid):
    now = datetime.now(UTC)
    for user_id, minutes in ((1, 1), (1, 9), (1, 11), (2, 1)):
        outreach.record_reveal(session, schedule_id=sid, contact_id=7, user_id=user_id, at=now - timedelta(minutes=minutes))
    session.commit()

    assert outreach.count_reveals(session, 1, since=now - timedelta(minutes=10)) == 2
    assert outreach.count_reveals(session, 2, since=now - timedelta(minutes=10)) == 1
    assert outreach.count_reveals(session, 3, since=now - timedelta(minutes=10)) == 0

    outreach.purge_schedule(session, sid)  # 일정을 지워도 감사 기록은 남는다
    session.commit()
    assert session.scalar(select(func.count()).select_from(ContactReveal)) == 4


def test_do_not_contact_numbers_agrees_with_is_do_not_contact(session, sid):
    sid2 = schedules.store(session, schedules.sample())
    _person(session, sid, "표시", phone="01000000101", do_not_contact=True)
    _person(session, sid2, "숨긴 표시", phone="01000000102", do_not_contact=True, hidden=True)
    _person(session, sid, "표시 없음", phone="01000000103")
    outreach.mark_do_not_contact(session, "010-0000-0104", reason="번호 기준")
    outreach.mark_do_not_contact(session, "1588-0199", reason="대표번호")
    session.commit()
    asked = ["01000000101", "010-0000-0102", "+82 10-0000-0103", "01000000104", "15880199", "1588-0199",
             "01000000105", "번호 아님", ""]

    found = outreach.do_not_contact_numbers(session, asked)

    assert found == {"01000000101", "01000000102", "01000000104", "15880199"}
    for number in asked:
        assert outreach.is_do_not_contact(session, number) == (normalize(number) in outreach.do_not_contact_numbers(
            session, [number])), number
    assert outreach.do_not_contact_numbers(session, []) == set()


def test_mark_do_not_contact_survives_a_concurrent_mark_of_the_same_number(session):
    """두 요청이 같은 번호를 거의 같이 수신 거부: 이 요청이 줄을 넣기 바로 전에 다른 요청이 같은 번호를 넣고 commit 했다.
    오류(500)가 아니라 한 줄로 남는다(먼저 남긴 까닭 그대로)."""
    engine = session.get_bind()
    path = engine.url.database
    raced: list[str] = []

    def other_request_first(conn, cursor, statement, params, context, executemany) -> None:
        if not raced and statement.lstrip().upper().startswith("INSERT") and "do_not_contact_numbers" in statement:
            raced.append(statement)
            with closing(sqlite3.connect(path)) as other:
                other.execute("INSERT INTO do_not_contact_numbers (number, reason, created_at) VALUES (?, ?, ?)",
                              (PHONE, "다른 요청", "2026-11-23 09:00:00"))
                other.commit()

    event.listen(engine, "before_cursor_execute", other_request_first)
    try:
        with Session(engine) as mine:
            outreach.mark_do_not_contact(mine, "010-0000-0199", reason="이 요청")
            mine.commit()
    finally:
        event.remove(engine, "before_cursor_execute", other_request_first)

    assert raced
    session.expire_all()
    assert [(r.number, r.reason) for r in session.scalars(select(DoNotContactNumber))] == [(PHONE, "다른 요청")]
