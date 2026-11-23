"""저장된 근거 다시 쓰기(app.store.evidence_reuse): 기존 DB 에도 retired 칸이 생기고 그전 근거도 찾는다.
최소 관련도는 검토(11-23) 재현 자료로 본다. 사람·현장은 모두 가상이다."""

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

# 다시 쓰기 전 모양(근거 표에 retired 칸 없음) + 11-23 에 잠깐 있던 낱말 색인(evidence_items_fts)과 트리거.
OLD_SHAPE = (
    "ALTER TABLE evidence_items DROP COLUMN retired",
    "CREATE VIRTUAL TABLE evidence_items_fts USING fts5(text)",
    ("CREATE TRIGGER evidence_items_fts_ai AFTER INSERT ON evidence_items BEGIN "
     "INSERT INTO evidence_items_fts(rowid, text) VALUES (new.id, new.title); END"),
    ("CREATE TRIGGER evidence_items_fts_ad AFTER DELETE ON evidence_items BEGIN "
     "DELETE FROM evidence_items_fts WHERE rowid = old.id; END"),
)


def test_existing_db_gets_the_column_finds_old_evidence_and_drops_the_old_index(tmp_path):
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
        assert db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'evidence_items_fts%'").fetchall() == []


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
    _save(session, "15층 철근콘크리트 골조 공기", "web", "15층 아파트 골조 공기 사례", "15층 골조 공기 6개월")
    _save(session, "레미콘 공급 리드타임", "business", "레미콘 공급 리드타임 안내", "주문 후 1일")
    _save(session, "도로공사 하도급 기간", "web", "한국도로공사 하도급 관리 기간", "하도급 계약 기간")
    _save(session, "지하주차장 방수 공사 기간", "web", "지하주차장 방수공사 공기", "방수공사 기간 2주")
    _save(session, "5층 사무동 골조 공기", "web", "5층 사무동 골조 공기 사례", "층당 10일")
    _save(session, "지하주차장 방수공사 사례", "web", "지하주차장 방수공사 공정 사례", "방수공사 2주")  # 낱말 안에만 있음
    return session


@pytest.mark.parametrize("query", ["철골 층당 골조 공기", "터널 골조 공기", "2024년 건설 표준 공기 기준", "골조 공사 기간",
                                   "공기", "골조", "목조 층당 골조 공기", "도로 건설 표준 공기",
                                   # 두 글자 낱말만 둘(흔한 말): 세 개는 되어야 찾는다
                                   "공사 기간", "층당 공기", "공기 측정", "골조 단가", "방수 기간",
                                   # 두 글자 낱말 셋이라 이 규칙으로는 못 막는다(한국도로공사 안의 도로·공사) — 검토에 알림
                                   pytest.param("도로 공사 기간", marks=pytest.mark.xfail(strict=True, reason="두 글자 낱말 셋"))])
def test_unrelated_saved_evidence_is_not_found(saved, query):
    assert evidence_reuse.find(saved, query, 5) == []


@pytest.mark.parametrize("query,title", [
    ("철근콘크리트 층당 골조 공기", "철근콘크리트 골조 공기 기준"),
    ("철근 콘크리트 골조 공기", "철근콘크리트 골조 공기 기준"),  # 띄어 쓴 말도 낱말 안에서 맞춘다
    ("착공 신고 기한", "건축물 착공신고"),
    ("착공신고의 처리 기한", "건축물 착공신고"),  # 조사(의)를 떼고 맞춘다
    ("타워크레인 임대 리드타임", "타워크레인 임대 리드타임"),
    ("레미콘 리드타임", "레미콘 공급 리드타임 안내"),
    ("크레인 임대", "타워크레인 임대 리드타임"),
    ("주차장 공사", "지하주차장 방수공사 공정 사례"),  # 두 낱말 모두 근거 낱말 안에만 있다
])
def test_related_saved_evidence_is_found(saved, query, title):
    assert title in [f.item.title for f in evidence_reuse.find(saved, query, 5)]


def test_newest_saved_evidence_comes_first(saved):
    titles = [f.item.title for f in evidence_reuse.find(saved, "철근 콘크리트 골조 공기", 5)]
    assert titles == ["15층 아파트 골조 공기 사례", "철근콘크리트 골조 공기 기준"]


def test_a_word_with_a_digit_matches_only_from_the_start(saved):
    assert [f.item.title for f in evidence_reuse.find(saved, "5층 골조 공기", 5)] == ["5층 사무동 골조 공기 사례"]
    assert [f.item.title for f in evidence_reuse.find(saved, "5층 철근콘크리트 골조 공기", 5)] == []  # 15층 근거 아님
    assert evidence_reuse._share(["3일"], "처리 기한 13일") == 0.0
    assert evidence_reuse._share(["3일"], "처리 기한 3일") == 1.0


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
