"""파일 저장(app.store.files, Task 47): 한 벌 저장·대화 연결·낱말 검색·숨김·완전 삭제, 계획 3 표·칸."""

import sqlite3
from contextlib import closing

import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.db import close_db, init_db
from app.store import files
from app.store.chats import create_chat
from app.store.schedules import NotFound
from app.store.tables import FileChunk, User

NEW_TABLES = {
    "files", "file_chunks", "file_chunks_fts", "file_axes", "axis_values", "chat_session_files",
    "info_connections", "reindex_jobs",
}

# 계획 2 가 만든 모양 그대로(모델 칸 없음)
OLD_CHAT_SESSIONS = """CREATE TABLE chat_sessions (
    id INTEGER NOT NULL, user_id INTEGER NOT NULL, title VARCHAR(100) NOT NULL, schedule_id INTEGER,
    created_at DATETIME NOT NULL, PRIMARY KEY (id))"""
CHAT_ROW = (1, 1, "A현장 공정 묻기", None, "2026-11-20 10:00:00")


@pytest.fixture
def admin_user(session) -> User:
    return session.scalars(select(User).where(User.login_id == "admin")).one()


def _txt(body: str) -> bytes:
    return body.encode("utf-8")


def test_save_upload_stores_once_by_content(session, admin_user):
    a = files.save_upload(session, _txt("골조 1층 기둥"), "메모.txt", admin_user)
    b = files.save_upload(session, _txt("골조 1층 기둥"), "다른이름.txt", admin_user)
    assert a.id == b.id and a.name == "메모.txt" and a.status == "extracted" and a.kind == "text"
    raw = Settings().data_dir / "files" / a.sha256[:2] / a.sha256
    assert raw.read_bytes() == _txt("골조 1층 기둥")


def test_link_and_session_files(session, admin_user):
    chat = create_chat(session, user_id=admin_user.id)
    f1 = files.save_upload(session, _txt("하나"), "1.txt", admin_user)
    f2 = files.save_upload(session, _txt("둘"), "2.txt", admin_user)
    files.link(session, chat.id, f2.id)
    files.link(session, chat.id, f1.id)
    files.link(session, chat.id, f2.id)  # 두 번 붙여도 한 줄
    assert [f.id for f in files.session_files(session, chat.id)] == [f2.id, f1.id]


def test_refused_name_raises(session, admin_user):
    with pytest.raises(files.Refused) as e:
        files.save_upload(session, b"x", "plan.xls", admin_user)
    assert "xlsx 로 저장해 주세요" in e.value.message


def test_keyword_search_finds_exact_token(session, admin_user):
    files.save_upload(session, _txt("콘크리트 강도는 C30 으로 한다. 슬래브 양생 7일."), "a.txt", admin_user)
    target = files.save_upload(session, _txt("기둥 콘크리트는 C24 를 쓴다."), "b.txt", admin_user)
    files.save_upload(session, _txt("전기 배관 매립 3일."), "c.txt", admin_user)
    hits = files.keyword_search(session, "C24", limit=5)
    assert hits[0].file_id == target.id and "C24" in hits[0].text and hits[0].file_name == "b.txt"
    assert all("C24" in h.text for h in hits)
    assert files.keyword_search(session, "콘크리트", limit=5, file_ids=[target.id])[0].file_id == target.id
    assert files.keyword_search(session, "콘크리트", limit=5, file_ids=[]) == []
    assert files.keyword_search(session, '"*:(', limit=5) == []  # FTS 문법 글자는 지운다


def test_korean_word_with_particle_is_found(session, admin_user):
    f = files.save_upload(session, _txt("골조공사는 다음 주에 시작한다."), "a.txt", admin_user)
    assert [h.file_id for h in files.keyword_search(session, "골조공사", limit=5)] == [f.id]


def test_soft_delete_hides_from_search_but_keeps_row(session, admin_user):
    f = files.save_upload(session, _txt("기둥 콘크리트는 C24 를 쓴다."), "b.txt", admin_user)
    files.soft_delete(session, f.id, admin_user)
    assert files.keyword_search(session, "C24", limit=5) == []
    kept = files.get(session, f.id)
    assert kept.deleted_at is not None and kept.name == "b.txt"
    assert session.scalars(select(FileChunk).where(FileChunk.file_id == f.id)).all() != []


def test_soft_delete_only_uploader_or_admin(session, admin_user):
    other = User(login_id="kim", name="김하늘", role="user", password_hash="x")
    session.add(other)
    session.commit()
    f = files.save_upload(session, _txt("관리자 메모"), "a.txt", admin_user)
    with pytest.raises(files.NotAllowed):
        files.soft_delete(session, f.id, other)
    mine = files.save_upload(session, _txt("내 메모"), "b.txt", other)
    files.soft_delete(session, mine.id, other)
    assert files.get(session, mine.id).deleted_at is not None


def test_reupload_of_hidden_file_shows_it_again(session, admin_user):
    f = files.save_upload(session, _txt("기둥 C24"), "b.txt", admin_user)
    files.soft_delete(session, f.id, admin_user)
    again = files.save_upload(session, _txt("기둥 C24"), "b.txt", admin_user)
    assert again.id == f.id and again.deleted_at is None
    assert files.keyword_search(session, "C24", limit=5)[0].file_id == f.id


def test_purge_removes_raw_chunks_and_index(session, admin_user):
    chat = create_chat(session, user_id=admin_user.id)
    f = files.save_upload(session, _txt("기둥 C24"), "b.txt", admin_user)
    files.link(session, chat.id, f.id)
    raw = Settings().data_dir / "files" / f.sha256[:2] / f.sha256
    files.purge(session, f.id)
    assert not raw.exists()
    with pytest.raises(NotFound):
        files.get(session, f.id)
    assert files.session_files(session, chat.id) == []
    assert session.execute(text("SELECT count(*) FROM file_chunks_fts")).scalar() == 0
    assert files.keyword_search(session, "C24", limit=5) == []


def test_existing_db_gets_new_tables_and_columns(tmp_path):
    path = tmp_path / "data" / "chronos.db"  # 시험 환경의 CHRONOS_DATA_DIR(tests/conftest.py)
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as db:
        db.execute(OLD_CHAT_SESSIONS)
        db.execute(f"INSERT INTO chat_sessions VALUES ({', '.join('?' * len(CHAT_ROW))})", CHAT_ROW)
        db.commit()
    init_db()
    init_db()  # 두 번 불러도 같다
    close_db()
    with closing(sqlite3.connect(path)) as db:
        cols = [row[1] for row in db.execute("PRAGMA table_info(chat_sessions)")]
        assert cols[-3:] == ["model_connection_id", "model_name", "model_routing"]
        assert db.execute("SELECT * FROM chat_sessions").fetchall() == [(*CHAT_ROW, None, None, None)]
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert NEW_TABLES <= names


def test_vision_and_embedding_defaults(session):
    from app.llm.assignments import Assignment, resolve, resolve_all

    assert resolve(session, "vision") == Assignment("vision", None, "liner-claude-router", "balanced")
    assert resolve(session, "embedding") == Assignment("embedding", None, "openai/text-embedding-3-small", None)
    assert [a.purpose for a in resolve_all(session)] == ["light", "normal", "hard", "longdoc"]  # 표 줄은 Task 52
