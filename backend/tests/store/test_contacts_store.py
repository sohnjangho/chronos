"""주소록 API(Task 72 고침 1차)가 쓰는 저장소: 번호 보기 기록 표(contact_reveals)·셈, 여러 번호의 수신 거부를 한 번에
(do_not_contact_numbers), 같은 번호를 두 요청이 동시에 수신 거부할 때(mark_do_not_contact). 번호는 모두 가상이다."""

import sqlite3
import threading
import unicodedata
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from app.db import close_db, init_db
from app.outreach.phone import normalize
from app.store import contact_reveals, contacts, outreach
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


def test_existing_reveal_table_gets_the_login_id_column(tmp_path):
    """login_id 칸 전에 만든 contact_reveals → init_db → 칸이 생기고(옛 줄은 비어 있음) 새 기록에 login_id 가 들어간다."""
    path = tmp_path / "data" / "chronos.db"
    path.parent.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name != "contact_reveals"])
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE contact_reveals (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                          "schedule_id INTEGER NOT NULL, contact_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
                          "at DATETIME NOT NULL)"))
        conn.execute(text("INSERT INTO contact_reveals (schedule_id, contact_id, user_id, at) "
                          "VALUES (1, 7, 1, '2026-11-20 09:00:00')"))
    engine.dispose()

    init_db()
    close_db()

    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        assert contact_reveals.record_reveal(session, schedule_id=1, contact_id=7, user_id=1, login_id="user1",
                                             limit=30, window=WINDOW, at=datetime(2026, 11, 20, 9, 5, tzinfo=UTC))
        session.commit()
        assert session.execute(select(ContactReveal.user_id, ContactReveal.login_id)
                               .order_by(ContactReveal.id)).all() == [(1, None), (1, "user1")]
    engine.dispose()


WINDOW = timedelta(minutes=10)


def _reveal(session: Session, sid: int, user_id: int, at: datetime, limit: int = 30) -> bool:
    return contact_reveals.record_reveal(session, schedule_id=sid, contact_id=7, user_id=user_id,
                                         login_id=f"user{user_id}", limit=limit, window=WINDOW, at=at)


def test_reveals_are_counted_per_user_since_a_time_and_outlive_the_schedule(session, sid):
    now = datetime.now(UTC)
    for user_id, minutes in ((1, 1), (1, 9), (1, 11), (2, 1)):
        assert _reveal(session, sid, user_id, now - timedelta(minutes=minutes))
    session.commit()

    assert contact_reveals.count_reveals(session, 1, since=now - WINDOW) == 2
    assert contact_reveals.count_reveals(session, 2, since=now - WINDOW) == 1
    assert contact_reveals.count_reveals(session, 3, since=now - WINDOW) == 0

    outreach.purge_schedule(session, sid)  # 일정을 지워도 감사 기록은 남는다
    session.commit()
    assert session.scalar(select(func.count()).select_from(ContactReveal)) == 4


def test_record_reveal_counts_and_inserts_in_one_step(session, sid):
    now = datetime.now(UTC)
    for minutes in (1, 2, 11):  # 창 밖 하나는 세지 않는다
        assert _reveal(session, sid, 1, now - timedelta(minutes=minutes), limit=3)
    assert _reveal(session, sid, 1, now, limit=3) is True  # 창 안 셋째
    assert _reveal(session, sid, 1, now, limit=3) is False  # 넷째 — 넣지 않음
    assert _reveal(session, sid, 2, now, limit=3) is True  # 다른 사용자
    session.commit()

    assert session.scalar(select(func.count()).select_from(ContactReveal).where(ContactReveal.user_id == 1)) == 4


def test_reveal_limit_holds_under_parallel_connections(session, sid):
    """창 안에 29번 본 사용자가 8개 연결에서 동시에 본다 → 하나만 기록되고 30줄에서 멈춘다."""
    now = datetime.now(UTC)
    session.add_all([ContactReveal(schedule_id=sid, contact_id=7, user_id=1, at=now - timedelta(minutes=1))
                     for _ in range(29)])
    session.commit()
    engine = session.get_bind()
    start = threading.Barrier(8)
    results: list[bool] = []

    def one_request() -> None:
        with Session(engine) as mine:
            start.wait()
            ok = _reveal(mine, sid, 1, datetime.now(UTC))
            mine.commit()
            results.append(ok)

    threads = [threading.Thread(target=one_request) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results) == [False] * 7 + [True]
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(ContactReveal)) == 30


def test_search_and_by_name_normalise_the_query_to_nfc(session, sid):
    _person(session, sid, "김공정", role_title="공무")
    _person(session, sid, "Nguyễn Văn An")
    session.commit()

    assert [c.name for c in contacts.search(session, sid, unicodedata.normalize("NFD", "김공정"))] == ["김공정"]
    assert [c.name for c in contacts.search(session, sid, unicodedata.normalize("NFD", "공무"))] == ["김공정"]
    assert [c.name for c in contacts.by_name(session, unicodedata.normalize("NFD", "김공정"))] == ["김공정"]
    assert [c.name for c in contacts.by_name(session, unicodedata.normalize("NFD", "Nguyễn Văn An"))] == [
        "Nguyễn Văn An"]


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
