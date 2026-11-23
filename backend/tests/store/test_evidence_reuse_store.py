"""저장된 근거 다시 쓰기의 표(app.store.tables): 기존 DB 에도 retired 칸과 낱말 색인(evidence_items_fts)이 생기고,
색인 전에 있던 근거도 찾을 수 있다. 사람·현장은 모두 가상이다."""

import sqlite3
from contextlib import closing

from sqlalchemy.orm import Session

from app import db as app_db
from app.db import close_db, init_db
from app.store import evidence_reuse
from app.store.evidence import link

# 다시 쓰기 전 모양: 근거 표에 retired 칸이 없고 낱말 색인·트리거도 없다.
OLD_SHAPE = (
    "DROP TRIGGER evidence_items_fts_ai", "DROP TRIGGER evidence_items_fts_ad", "DROP TABLE evidence_items_fts",
    "ALTER TABLE evidence_items DROP COLUMN retired",
)


def test_existing_db_gets_the_column_and_indexes_old_evidence(tmp_path):
    path = tmp_path / "data" / "chronos.db"  # 시험 환경의 CHRONOS_DATA_DIR(tests/conftest.py)
    init_db()
    close_db()
    with closing(sqlite3.connect(path)) as db:
        for sql in OLD_SHAPE:
            db.execute(sql)
        db.execute("INSERT INTO evidence_searches (id, query, mode, ok, result_count, latency_ms, created_at) "
                   "VALUES (1, '착공신고 처리 기한', 'legal', 1, 1, 0, datetime('now'))")
        db.execute("INSERT INTO evidence_items (id, search_id, title, url, hostname, description, extra_json, created_at) "
                   "VALUES (1, 1, '건축물 착공신고', 'https://law.example/1', 'law.example', '처리 기한 3일', '{}', datetime('now'))")
        db.commit()
    init_db()
    init_db()  # 두 번 불러도 같다
    try:
        with Session(app_db._engine) as session:
            link(session, evidence_ids=[1], draft_id=1, assumption_label="착공신고 기간")
            session.commit()
            [found] = evidence_reuse.find(session, "착공신고 처리 기한", "legal", 5)
            assert (found.item.id, found.item.retired) == (1, False)
    finally:
        close_db()
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT rowid, text FROM evidence_items_fts").fetchall() == [
            (1, "건축물 착공신고 처리 기한 3일 착공신고 처리 기한")]
