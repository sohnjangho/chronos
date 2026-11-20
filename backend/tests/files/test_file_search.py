"""뜻+낱말 검색(app.files.search, Task 48): RRF 로 합치기·축 거르기·붙인 파일 먼저·Qdrant 가 꺼졌을 때."""

import httpx
import pytest

from app.files import jobs, vectors
from app.files.search import search
from app.store import files
from app.store.tables import FileAxis
from tests.embed_doubles import SMALL
from tests.llm_doubles import add_connection

NOT_READY = "뜻 검색 준비 안 됨"


async def test_meaning_search_beats_keyword_for_paraphrase(session, ready, put):
    winter = put("동절기 콘크리트 타설은 보온 양생을 한다.")
    strength = put("콘크리트 강도 C30.")
    put("전기 배관 매립.")
    await jobs.drain()
    assert files.keyword_search(session, "겨울 콘크리트", 5)[0].file_id == strength.id  # 낱말로만 찾으면 강도 조각이 1위

    hits = await search(session, "겨울 콘크리트")
    assert [(h.file_id, h.source) for h in hits] == [(winter.id, "both"), (strength.id, "keyword")]
    assert hits[0].score == pytest.approx(1 / 61 + 1 / 62) and hits[1].score == pytest.approx(1 / 61)  # RRF k=60
    assert hits[0].locator == "본문" and hits[0].text == "동절기 콘크리트 타설은 보온 양생을 한다."
    assert hits[0].chunk_id == files.chunks_of(session, winter.id)[0].id


async def test_keyword_still_finds_exact_token_when_vector_misses(session, ready, put):
    snet = put("SNET 망 접속 절차서")
    put("동절기 타설 계획")
    await jobs.drain()
    hits = await search(session, "SNET")
    assert [(h.file_id, h.source) for h in hits] == [(snet.id, "keyword")]


async def test_filters_by_axis_values(session, ready, put):
    a, b = put("A현장 동절기 타설"), put("B현장 동절기 타설")
    session.add_all([
        FileAxis(file_id=a.id, axis="현장", value="A현장"), FileAxis(file_id=a.id, axis="공종", value="골조"),
        FileAxis(file_id=b.id, axis="현장", value="B현장"),
    ])
    session.commit()
    await jobs.drain()
    assert {h.file_id for h in await search(session, "겨울 타설", filters={"현장": ["A현장"]})} == {a.id}
    both = await search(session, "겨울 타설", filters={"현장": ["A현장", "B현장"]})
    assert {h.file_id for h in both} == {a.id, b.id}
    assert {h.file_id for h in await search(session, "겨울", filters={"현장": ["A현장", "B현장"], "공종": ["골조"]})} == {a.id}
    assert await search(session, "겨울 타설", filters={"현장": ["C현장"]}) == []
    assert len(await search(session, "겨울 타설", filters={"현장": []})) == 2  # 빈 목록은 거르지 않는다


async def test_qdrant_down_keeps_keyword_search_and_requeues(session, embedder, put, monkeypatch):
    add_connection(session)
    monkeypatch.setattr(vectors, "STORE", vectors.Store("http://127.0.0.1:1"))  # Qdrant 가 꺼져 있다
    f = put("동절기 콘크리트 타설")
    await jobs.drain()
    session.expire_all()
    assert (f.status, f.reason, jobs.waiting()) == ("extracted", NOT_READY, [f.id])
    hits = await search(session, "콘크리트")
    assert hits and {h.source for h in hits} == {"keyword"}
    assert embedder.requests == []  # Qdrant 가 안 되면 임베딩도 부르지 않는다

    monkeypatch.setattr(vectors, "STORE", vectors.Store(":memory:"))  # 서버가 돌아왔다
    assert await jobs.recheck() == 1
    await jobs.drain()
    session.expire_all()
    assert (f.status, f.reason, jobs.waiting()) == ("indexed", None, [])
    assert [(h.file_id, h.source) for h in await search(session, "겨울")] == [(f.id, "vector")]


async def test_prefer_file_ids_lifts_attached_files(session, ready, put):
    put("동절기 타설 하나")
    put("동절기 타설 둘")
    await jobs.drain()
    plain = await search(session, "동절기 타설")
    second = plain[1]
    lifted = await search(session, "동절기 타설", prefer_file_ids=[second.file_id])
    assert lifted[0].file_id == second.file_id and lifted[0].score == pytest.approx(second.score * 1.5)


async def test_hidden_files_and_limit(session, ready, put, admin_user):
    hidden = put("동절기 타설 숨김")
    for i in range(3):
        put(f"동절기 타설 {i}")
    await jobs.drain()
    files.soft_delete(session, hidden.id, admin_user)
    hits = await search(session, "겨울", limit=2)
    assert len(hits) == 2 and hidden.id not in {h.file_id for h in await search(session, "겨울")}


async def test_query_embedding_failure_falls_back_to_keyword(session, ready, put, embedder):
    f = put("동절기 콘크리트 타설")
    await jobs.drain()
    embedder.push(httpx.Response(500))
    assert [(h.file_id, h.source) for h in await search(session, "콘크리트")] == [(f.id, "keyword")]
    assert embedder.models[-1] == SMALL


async def test_vectors_off_is_keyword_only(session, ready, put, monkeypatch):
    f = put("동절기 콘크리트 타설")
    monkeypatch.setattr(vectors, "STORE", None)  # CHRONOS_QDRANT_URL 빈 값
    assert [(h.file_id, h.source) for h in await search(session, "콘크리트")] == [(f.id, "keyword")]
