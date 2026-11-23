"""저장된 근거 다시 쓰기의 표(app.store.tables): 기존 DB 에도 retired 칸과 낱말 색인(evidence_items_fts)이 생기고,
색인 전에 있던 근거도 찾을 수 있다. 사람·현장은 모두 가상이다."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app import db as app_db
from app.db import close_db, init_db
from app.llm.search import SearchHit
from app.store import evidence_reuse
from app.store.evidence import link, record_search

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
            [found] = evidence_reuse.find(session, "착공신고 처리 기한", 5)
            assert (found.item.id, found.item.retired) == (1, False)
    finally:
        close_db()
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT rowid, text FROM evidence_items_fts").fetchall() == [
            (1, "건축물 착공신고 처리 기한 3일 착공신고 처리 기한")]


# ── 최소 관련도(검토 11-23 재현 자료): 물음 낱말은 모두 맞아야 하고, 띄어쓰기·조사는 봐준다 ─────────────


def _save(session, query: str, mode: str, title: str, description: str) -> str:
    _, [item] = record_search(session, chat_session_id=None, query=query, mode=mode, ok=True, error_code=None,
                              latency_ms=0, hits=[SearchHit(title=title, url=f"https://x/{title}", hostname="x",
                                                            description=description, date=None)])
    link(session, evidence_ids=[item.id], draft_id=1, assumption_label="a")
    session.commit()
    return title


@pytest.fixture
def saved(session) -> Session:
    _save(session, "철근콘크리트 층당 골조 공기", "web", "철근콘크리트 골조 공기 기준", "층당 골조 8~12일")
    _save(session, "아파트 골조 공사비 단가", "web", "아파트 골조 공사비 단가 2024", "평당 공사비")
    _save(session, "건축물 착공신고 처리 기한", "legal", "건축물 착공신고", "처리 기한 3일")
    _save(session, "타워크레인 임대 리드타임", "business", "타워크레인 임대 리드타임", "4~6주")
    _save(session, "2019년 건설 표준 공기 기준", "web", "2019년 건설공사 표준 공기 산정 기준", "공사 기간 산정")
    _save(session, "공기질 측정 기준", "web", "실내 공기질 측정 기준", "공기질 관리법")
    return session


@pytest.mark.parametrize("query", ["철골 층당 골조 공기", "터널 골조 공기", "2024년 건설 표준 공기 기준", "골조 공사 기간",
                                   "공기", "골조", "목조 층당 골조 공기", "도로 건설 표준 공기"])
def test_unrelated_saved_evidence_is_not_found(saved, query):
    assert evidence_reuse.find(saved, query, 5) == []


@pytest.mark.parametrize("query,title", [
    ("철근콘크리트 층당 골조 공기", "철근콘크리트 골조 공기 기준"),
    ("철근 콘크리트 골조 공기", "철근콘크리트 골조 공기 기준"),  # 띄어 쓴 말도 낱말 안에서 맞춘다
    ("착공 신고 기한", "건축물 착공신고"),
    ("착공신고의 처리 기한", "건축물 착공신고"),  # 조사(의)를 떼고 맞춘다
    ("타워크레인 임대 리드타임", "타워크레인 임대 리드타임"),
])
def test_related_saved_evidence_is_found(saved, query, title):
    assert [f.item.title for f in evidence_reuse.find(saved, query, 5)] == [title]


def test_found_evidence_says_its_mode_and_query(saved):
    [found] = evidence_reuse.find(saved, "착공신고 처리 기한", 5)
    assert (found.mode, found.found_by) == ("legal", "건축물 착공신고 처리 기한")


def test_age_is_counted_in_seoul_days_and_the_window_is_30_times_24_hours(saved):
    [found] = evidence_reuse.find(saved, "착공신고 처리 기한", 5)
    item = found.item
    item.created_at = datetime(2026, 11, 20, 14, 30, tzinfo=UTC)  # 서울 11-20 23:30
    saved.commit()
    [found] = evidence_reuse.find(saved, "착공신고 처리 기한", 5, now=datetime(2026, 11, 20, 15, 30, tzinfo=UTC))
    assert (found.searched_at, found.age_days) == ("2026-11-20", 1)  # 서울로는 다음 날(11-21 00:30)
    edge = datetime(2026, 11, 20, 14, 30, tzinfo=UTC) + timedelta(days=30)
    assert evidence_reuse.find(saved, "착공신고 처리 기한", 5, now=edge - timedelta(minutes=1)) != []
    assert evidence_reuse.find(saved, "착공신고 처리 기한", 5, now=edge + timedelta(minutes=1)) == []
