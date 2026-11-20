"""파일 뒤 작업 줄(app.files.jobs, Task 48): 임베딩해 넣기·실패와 다시 하기·다시 넣기(모델 바꾸기)·서버 시작·완전 삭제."""

import asyncio
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.files import extract as extracting
from app.files import jobs, vectors
from app.files.search import search
from app.main import app
from app.store import files
from app.store.tables import FileChunk, FileRow, ReindexJob, Setting
from tests.embed_doubles import LARGE, NEW, OLD, SMALL, vector
from tests.llm_doubles import KEY

NOT_READY = "뜻 검색 준비 안 됨"
SCANNED = "스캔 문서라 글을 읽을 수 없습니다(OCR 미지원)"


class SpyStore(vectors.Store):
    """메모리 Qdrant + 어느 컬렉션에 어느 조각을 넣었는지 적는다."""

    def __init__(self) -> None:
        super().__init__(":memory:", "t")
        self.upserts: list[tuple[str, int]] = []

    def upsert(self, collection, points):
        self.upserts.extend((collection, p.chunk_id) for p in points)
        super().upsert(collection, points)


def _chunk_ids(session, file_id: int) -> list[int]:
    return [c.id for c in files.chunks_of(session, file_id)]


async def test_indexing_puts_chunks_in_the_active_collection(session, ready, put, store):
    f = put("동절기 타설")
    assert [(i.kind, i.id) for i in jobs._queue] == [("file", f.id)]
    await jobs.drain()
    session.expire_all()
    assert (f.status, f.reason) == ("indexed", None)
    assert store.collections() == [OLD]
    assert store.search(OLD, vector("겨울", SMALL), 5) == [(_chunk_ids(session, f.id)[0], pytest.approx(1.0))]


async def test_embed_failure_leaves_extracted_with_reason(session, ready, put, embedder):
    embedder.push(httpx.Response(500))
    f = put("동절기 타설")
    await jobs.drain()
    session.expire_all()
    assert (f.status, f.reason) == ("extracted", NOT_READY)
    assert len(embedder.requests) == 1 and jobs.waiting() == []  # 30초 뒤 다시 할 차례(아직 다시 넣기 줄 아님)


async def test_failed_file_is_retried_three_times_then_waits(session, ready, put, embedder, monkeypatch):
    monkeypatch.setattr(jobs, "RETRY_S", 0)
    embedder.push(*[httpx.Response(500)] * 4)
    f = put("동절기 타설")
    await jobs.drain()
    assert len(embedder.requests) == 4 and jobs.waiting() == [f.id]


async def test_retry_success_clears_only_our_reason(session, ready, put, embedder, monkeypatch):
    monkeypatch.setattr(jobs, "RETRY_S", 0)
    embedder.push(httpx.Response(500))
    f = put("동절기 타설")
    await jobs.drain()
    session.expire_all()
    assert (f.status, f.reason) == ("indexed", None)

    scanned = put("철근 배근 스캔")
    scanned.reason = SCANNED  # 글 뽑기가 단 주의는 지우지 않는다
    session.commit()
    embedder.push(httpx.Response(500))
    await jobs.drain()
    session.expire_all()
    assert (scanned.status, scanned.reason) == ("indexed", SCANNED)


async def test_file_without_chunks_is_indexed_without_embedding(session, ready, put, embedder):
    f = put("   \n")
    await jobs.drain()
    session.expire_all()
    assert f.status == "indexed" and embedder.requests == []


async def test_purged_file_in_the_queue_is_skipped(session, ready, put, embedder):
    f = put("동절기 타설")
    files.purge(session, f.id)
    await jobs.drain()
    assert embedder.requests == []


async def test_reindex_switches_after_done(session, ready, put, store, embedder):
    winter = put("동절기 타설")
    put("철근 배근 검측")
    await jobs.drain()
    assert jobs.enqueue_reindex(LARGE) == {"job_id": 1, "total": 2}
    job = session.get(ReindexJob, 1)
    assert (job.model, job.status, job.total, job.done) == (LARGE, "running", 2, 0)

    embedder.bodies.clear()
    assert (await search(session, "겨울"))[0].file_id == winter.id  # 진행 중: 옛 모델로 옛 컬렉션을 찾는다
    assert embedder.models == [SMALL] and jobs.active_model(session) == SMALL

    await jobs.drain()
    session.expire_all()
    assert (job.status, job.done, job.collection) == ("done", 2, NEW) and job.finished_at is not None
    assert store.collections() == [NEW]  # 끝나면 옛 컬렉션을 지운다
    embedder.bodies.clear()
    assert (await search(session, "겨울"))[0].file_id == winter.id
    assert embedder.models == [LARGE] and jobs.active_model(session) == LARGE


async def test_upload_during_reindex_lands_in_both(session, ready, put, monkeypatch):
    spy = SpyStore()
    monkeypatch.setattr(vectors, "STORE", spy)
    put("철근 배근 검측")
    await jobs.drain()
    jobs.enqueue_reindex(LARGE)
    late = put("동절기 타설")
    await jobs.drain()
    late_chunk = _chunk_ids(session, late.id)[0]
    assert sorted(c for c, chunk_id in spy.upserts if chunk_id == late_chunk) == [NEW, OLD]
    hits = await search(session, "겨울")  # 바꾸기 끝난 뒤 새 컬렉션에서 나온다
    assert [(h.file_id, h.source) for h in hits] == [(late.id, "vector")] and spy.collections() == [NEW]


async def test_reindex_moves_in_batches_and_lets_files_in_between(session, ready, put, embedder, monkeypatch):
    monkeypatch.setattr(jobs, "BATCH", 2)
    for i in range(5):
        put(f"철근 배근 {i}")
    await jobs.drain()
    jobs.enqueue_reindex(LARGE)
    embedder.bodies.clear()
    await jobs.drain()
    assert [len(b["input"]) for b in embedder.bodies] == [2, 2, 1]
    assert session.get(ReindexJob, 1).done == 5


async def test_enqueue_reindex_refuses_when_it_cannot_start(session, ready, monkeypatch):
    jobs.enqueue_reindex(LARGE)
    with pytest.raises(jobs.ReindexRefused) as e:  # 이미 다시 넣는 중
        jobs.enqueue_reindex(SMALL)
    assert e.value.code == "running"
    session.get(ReindexJob, 1).status = "done"
    session.commit()
    monkeypatch.setattr(vectors, "STORE", vectors.Store("http://127.0.0.1:1", "t"))
    with pytest.raises(jobs.ReindexRefused) as e:  # Qdrant 가 꺼져 있다
        jobs.enqueue_reindex(SMALL)
    assert e.value.code == "down"
    monkeypatch.setattr(vectors, "STORE", None)
    with pytest.raises(jobs.ReindexRefused) as e:  # 뜻 검색을 껐다
        jobs.enqueue_reindex(SMALL)
    assert e.value.code == "off"
    assert len(session.scalars(select(ReindexJob)).all()) == 1


async def test_failed_reindex_keeps_the_old_collection(session, ready, put, store, embedder, monkeypatch):
    monkeypatch.setattr(jobs, "RETRY_S", 0)
    f = put("동절기 타설")
    await jobs.drain()
    jobs.enqueue_reindex(LARGE)
    embedder.push(*[httpx.Response(500)] * 4)
    await jobs.drain()
    session.expire_all()
    job = session.get(ReindexJob, 1)
    assert job.status == "failed" and job.finished_at is not None
    assert store.collections() == [OLD] and jobs.active_model(session) == SMALL
    assert (await search(session, "겨울"))[0].file_id == f.id


async def test_reload_reads_leftover_work_from_the_db(session, ready, put, store, monkeypatch):
    f = put("동절기 타설")
    monkeypatch.setattr(jobs, "_queue", [])  # 서버가 다시 떴다 — 메모리 줄은 비었다
    session.add(ReindexJob(model=LARGE, collection="", total=0))
    session.commit()
    jobs.reload()
    assert [(i.kind, i.id) for i in jobs._queue] == [("file", f.id), ("reindex", 1)]
    await jobs.drain()
    session.expire_all()
    job = session.get(ReindexJob, 1)
    assert f.status == "indexed" and (job.status, job.total, job.done) == ("done", 1, 1)
    assert store.collections() == [NEW]


async def test_worker_started_at_startup_indexes_uploads(session, ready, put, monkeypatch):
    monkeypatch.setenv("CHRONOS_QDRANT_URL", ":memory:")
    jobs.start()
    try:
        f = put("동절기 타설")
        for _ in range(100):
            await asyncio.sleep(0.02)
            session.expire_all()
            if f.status == "indexed":
                break
        assert f.status == "indexed"
    finally:
        await jobs.stop()


async def test_start_runs_the_worker_even_when_vectors_are_off(session, monkeypatch):
    monkeypatch.setenv("CHRONOS_QDRANT_URL", "")
    monkeypatch.setattr(vectors, "STORE", None)
    jobs.start.__wrapped__()  # 진짜 start(tests/conftest.py 는 시험에서 주소가 없으면 띄우지 않는다)
    try:
        assert vectors.STORE is None and jobs._task is not None  # 뜻 검색만 끄고 일꾼은 돈다(분류는 Task 49)
    finally:
        await jobs.stop()


async def test_purge_also_removes_vectors(client, admin, session, ready, put, store):
    f = put("동절기 타설")
    await jobs.drain()
    assert client.delete(f"/api/files/{f.id}?purge=1", headers=admin).status_code == 204
    assert store.search(OLD, vector("겨울", SMALL), 5) == []


async def test_no_key_in_logs_or_errors(session, ready, put, embedder, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(jobs, "RETRY_S", 0)
    embedder.push(*[httpx.Response(401, json={"error": f"invalid key {KEY}"})] * 4)
    f = put("동절기 타설")
    await jobs.drain()
    session.expire_all()
    assert f.reason == NOT_READY and jobs.waiting() == [f.id]
    assert KEY not in caplog.text and "bad_key" in caplog.text
    assert KEY not in repr(session.execute(text("SELECT * FROM llm_calls")).all())


def test_conftest_wrapper_keeps_the_lifespan_worker_off_in_tests(monkeypatch):
    # 서버의 일꾼은 주소가 없어도 돈다. 여기서 꺼져 있는 것은 tests/conftest.py 의 jobs.start 감쌈 때문이다
    # (시험이 jobs.drain 으로 돌리는 작업 줄을 앱 스레드의 일꾼이 가로채지 않게). 진짜 동작은 아래 시험.
    assert Settings().qdrant_url == ""
    with TestClient(app):
        assert jobs._task is None
    monkeypatch.setenv("CHRONOS_QDRANT_URL", ":memory:")
    monkeypatch.setattr(vectors, "STORE", None)
    with TestClient(app):
        assert jobs._task is not None and vectors.STORE is not None
    assert jobs._task is None


def test_lifespan_starts_and_stops_the_worker_without_vectors(monkeypatch):
    monkeypatch.setattr(jobs, "start", jobs.start.__wrapped__)  # 감쌈 없이 진짜 start
    monkeypatch.setattr(vectors, "STORE", None)
    assert Settings().qdrant_url == ""
    with TestClient(app):
        assert jobs._task is not None and vectors.STORE is None  # 뜻 검색만 꺼지고 일꾼은 돈다
    assert jobs._task is None


async def test_worker_survives_an_unexpected_error(session, ready, put, embedder, monkeypatch):
    monkeypatch.setenv("CHRONOS_QDRANT_URL", ":memory:")
    monkeypatch.setattr(jobs, "_note_not_ready", lambda file_id: 1 / 0)  # 실패 처리 자체가 깨졌다(예: DB 잠김)
    embedder.push(httpx.Response(500))
    jobs.start()
    try:
        put("철근 배근")
        good = put("동절기 타설")
        for _ in range(100):
            await asyncio.sleep(0.02)
            session.expire_all()
            if good.status == "indexed":
                break
        assert good.status == "indexed"  # 일꾼은 멈추지 않고 다음 작업을 한다
    finally:
        await jobs.stop()


def _embedding_model_listed(session, conn) -> dict:
    conn.models_json = [{"id": LARGE, "name": LARGE, "vendor": "openai", "vendor_name": "OpenAI", "context_length": 8192,
                         "chat": False, "price": None, "embedding": True}]
    session.commit()
    return {"purpose": "embedding", "connection_id": conn.id, "model": LARGE, "routing_strategy": None}


def test_task51_put_assignments_starts_a_real_reindex(client, admin, session, ready, put):
    put("동절기 타설")
    item = _embedding_model_listed(session, ready)
    r = client.put("/api/llm/assignments", json={"items": [item]}, headers=admin)
    assert r.status_code == 200 and r.json()["reindex"] == {"job_id": 1, "total": 1}
    assert [(i.kind, i.id) for i in jobs._queue][-1] == ("reindex", 1)


def test_task51_put_assignments_is_refused_when_qdrant_is_down(client, admin, session, ready, monkeypatch):
    monkeypatch.setattr(vectors, "STORE", vectors.Store("http://127.0.0.1:1", "t"))
    r = client.put("/api/llm/assignments", json={"items": [_embedding_model_listed(session, ready)]}, headers=admin)
    assert r.status_code == 503 and r.json()["message"] == "다시 넣기를 시작할 수 없어 임베딩 모델을 바꾸지 않았습니다."
    assert session.scalars(select(ReindexJob)).all() == []


# ── Fix round 1 ─────────────────────────────────────────────────────


def _many_files(session, admin_user, n: int) -> list[int]:
    """글 조각이 하나씩 있는 extracted 파일 n 개를 DB 에 바로 넣고 작업 줄에 넣는다(올리기보다 빠르게)."""
    rows = [FileRow(sha256=f"{i:064x}", name=f"{i}.txt", ext="txt", kind="text", size=1, status="extracted",
                    uploaded_by=admin_user.id) for i in range(n)]
    session.add_all(rows)
    session.flush()
    session.add_all([FileChunk(file_id=r.id, seq=0, locator="본문", text=f"철근 배근 {r.id}") for r in rows])
    session.commit()
    for r in rows:
        jobs.enqueue(r.id)
    return [r.id for r in rows]


async def test_hopeless_errors_wait_without_retries_and_each_sweep_tries_once(
    session, ready, embedder, admin_user, monkeypatch
):
    monkeypatch.setattr(jobs, "RETRY_S", 0)  # 다시 하기가 있으면 곧바로 보이게
    n = 1000
    ids = _many_files(session, admin_user, n)
    embedder.push(*[httpx.Response(401)] * n)  # bad_key — 다시 해도 나아지지 않는다
    await jobs.drain()
    assert len(embedder.requests) == n and jobs.waiting() == ids  # 파일마다 1번(4번이 아니라)

    embedder.push(*[httpx.Response(503)] * n)  # 다시 넣기 줄에서 꺼낸 것은 다시 할 수 있는 실패라도 한 번만
    assert await jobs.recheck() == n
    await jobs.drain()
    assert len(embedder.requests) == 2 * n and jobs.waiting() == ids and jobs._queue == []


async def test_slow_extraction_does_not_hold_the_write_lock(session, put, monkeypatch):
    other = put("철근 배근")
    real = extracting.extract
    seen = []

    def slow_extract(path, kind):
        jobs._note_not_ready(other.id)  # 글을 뽑는 동안 일꾼이 다른 파일을 기록한다(잠금을 쥐고 있으면 5초 뒤 locked)
        seen.append(kind)
        return real(path, kind)

    monkeypatch.setattr(extracting, "extract", slow_extract)
    f = put("동절기 타설")
    session.expire_all()
    assert seen == ["text"] and other.reason == NOT_READY and f.status == "extracted"


async def test_lock_error_never_drops_a_file_from_the_queue(session, ready, put, embedder, monkeypatch):
    def locked(file_id):
        raise OperationalError("UPDATE files", {}, Exception("database is locked"))

    monkeypatch.setattr(jobs, "_note_not_ready", locked)
    embedder.push(httpx.Response(500))
    f = put("동절기 타설")
    await jobs.drain()
    assert [(i.kind, i.id, i.retries) for i in jobs._queue] == [("file", f.id, 1)]


async def test_finish_drops_only_this_instances_collections(session, ready, put, store, monkeypatch):
    other = vectors.Store(":memory:", "u", client=store.client)  # 같은 Qdrant 를 쓰는 다른 서버
    other.upsert(other.collection_for(SMALL, 8), [vectors.Point(1, 1, vector("동절기", SMALL))])
    put("동절기 타설")
    await jobs.drain()
    jobs.enqueue_reindex(LARGE)
    await jobs.drain()
    assert store.collections() == [NEW] and other.collections() == ["chunks__u__openai_text-embedding-3-small__8"]


def test_instance_id_is_made_once_and_redoes_old_vectors(session, put):
    f = put("동절기 타설")
    f.status = "indexed"  # 앞말 없는 컬렉션에 넣었던 파일(이 고침 전)
    session.commit()
    first = jobs._instance()
    session.expire_all()
    assert f.status == "extracted" and session.get(Setting, jobs.INSTANCE_KEY).value == first and len(first) == 8
    f.status = "indexed"
    session.commit()
    assert jobs._instance() == first
    session.expire_all()
    assert f.status == "indexed"  # 두 번째부터는 그대로


async def test_bad_qdrant_url_turns_meaning_search_off(session, monkeypatch, caplog):
    monkeypatch.setenv("CHRONOS_QDRANT_URL", "ftp://x")
    monkeypatch.setattr(vectors, "STORE", None)
    jobs.start()  # 서버는 뜬다 — 뜻 검색만 끄고 일꾼은 돈다(분류는 Task 49)
    try:
        assert vectors.STORE is None and jobs._task is not None and "CHRONOS_QDRANT_URL" in caplog.text
    finally:
        await jobs.stop()


def test_task51_put_assignments_is_409_while_reindex_runs(client, admin, session, ready):
    jobs.enqueue_reindex(SMALL)
    r = client.put("/api/llm/assignments", json={"items": [_embedding_model_listed(session, ready)]}, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "already_running"
    assert session.scalar(select(ReindexJob.model).order_by(ReindexJob.id.desc())) == SMALL
