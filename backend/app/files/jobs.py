"""파일 뒤 작업 줄: 글 조각을 임베딩해 뜻 검색(Qdrant)에 넣기 · 임베딩 모델 바꾸기(다시 넣기).

- 줄은 메모리에 있고 일꾼 하나가 하나씩 차례로 한다(서버가 뜰 때 start, 닫을 때 stop). 서버가 다시 뜨면 DB 에서 다시 읽는다
  (reload): status extracted 인 파일 · status running 인 다시 넣기(처음부터 — 같은 조각은 바꿔 넣을 뿐이다).
- 파일 하나: 조각을 지금 모델(active_model)로 임베딩해 그 컬렉션에 넣고 status indexed. 다시 넣기 중이면 새 모델 컬렉션에도
  넣는다(두 컬렉션 모두). 조각이 없는 파일은 임베딩 없이 indexed.
- 실패하면 status extracted + reason 「뜻 검색 준비 안 됨」(다른 까닭이 이미 있으면 그대로)이고 RETRY_S 뒤 다시(MAX_RETRIES 번).
  그래도 안 되거나 Qdrant 가 안 되면 「다시 넣기」 줄(waiting)에 남는다. RECHECK_S 마다 Qdrant 가 되면 작업 줄로 옮긴다.
- 다시 넣기(enqueue_reindex): reindex_jobs 한 줄을 바로 만든다. 시작 때 가장 큰 조각 id 까지를 BATCH 개씩 새 모델로 새
  컬렉션에 넣는다 — 한 걸음마다 줄 끝으로 돌아가므로 그 사이 들어온 파일 작업이 먼저 돈다. 다 넣으면 done → 검색이 새 모델·
  새 컬렉션으로 바뀌고 다른 chunks__ 컬렉션은 지운다. 한 걸음이 MAX_RETRIES 번 다시 해도 안 되면 failed(검색은 옛 그대로).
- 지금 모델(active_model) = 마지막으로 끝난(done) 다시 넣기의 모델, 없으면 기본 임베딩 모델. 배정(assignments)은 바꾸기를
  시작할 때 바로 새 모델이 되므로, 검색·파일 넣기는 배정이 아니라 이것을 따른다.
"""

import asyncio
import contextlib
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.files import vectors
from app.llm.assignments import DEFAULT_ASSIGNMENTS
from app.llm.embeddings import EmbedFailed, embed
from app.store.tables import FileChunk, FileRow, ReindexJob

logger = logging.getLogger(__name__)

NOT_READY = "뜻 검색 준비 안 됨"
BATCH = 64  # 다시 넣기 한 걸음의 조각 수
RETRY_S = 30.0
MAX_RETRIES = 3
RECHECK_S = 300.0  # 「다시 넣기」 줄을 볼 간격(5분)


class ReindexRefused(Exception):
    """다시 넣기를 시작할 수 없다(Qdrant 에 연결할 수 없음·뜻 검색 꺼짐·이미 다시 넣는 중)."""


class _QdrantDown(Exception):
    """Qdrant 를 쓸 수 없다 — 다시 하지 않고 「다시 넣기」 줄에 둔다."""


@dataclass
class _Item:
    kind: Literal["file", "reindex"]
    id: int
    retries: int = 0
    not_before: float = 0.0  # time.monotonic() — 이때부터 한다


# 업로드는 스레드에서 enqueue 를 부른다. 줄·다시 넣기 줄·커서는 _lock 안에서만 바꾼다(제자리에서 — 시험이 바꿔 끼운다).
_lock = threading.Lock()
_queue: list[_Item] = []
_waiting: set[int] = set()  # 「다시 넣기」 줄(파일 id)
_cursors: dict[int, tuple[int, int]] = {}  # 다시 넣기 id → (마지막으로 넣은 조각 id, 시작 때 가장 큰 조각 id)
_loop: asyncio.AbstractEventLoop | None = None
_wake: asyncio.Event | None = None
_task: asyncio.Task | None = None


def _db():
    return contextmanager(get_session)()


def _push(item: _Item) -> None:
    with _lock:
        if not any(q.kind == item.kind and q.id == item.id for q in _queue):
            _queue.append(item)
        if item.kind == "file":
            _waiting.discard(item.id)
    loop, wake = _loop, _wake
    if loop is not None and wake is not None:
        loop.call_soon_threadsafe(wake.set)


def enqueue(file_id: int) -> None:
    """글을 뽑은 파일을 작업 줄에 넣는다(어느 스레드에서 불러도 된다)."""
    _push(_Item("file", file_id))


def waiting() -> list[int]:
    """「다시 넣기」 줄의 파일 id(Qdrant 가 안 되거나 다시 해도 실패한 파일)."""
    with _lock:
        return sorted(_waiting)


def active_model(session: Session) -> str:
    """검색·파일 넣기에 쓰는 임베딩 모델(맨 위 설명)."""
    done = select(ReindexJob.model).where(ReindexJob.status == "done").order_by(ReindexJob.id.desc()).limit(1)
    return session.scalar(done) or DEFAULT_ASSIGNMENTS["embedding"][0]


def _running(session: Session) -> ReindexJob | None:
    return session.scalar(select(ReindexJob).where(ReindexJob.status == "running").order_by(ReindexJob.id).limit(1))


def _span(session: Session) -> tuple[int, int]:
    """(조각 수, 가장 큰 조각 id)."""
    count, top = session.execute(select(func.count(FileChunk.id), func.max(FileChunk.id))).one()
    return count, top or 0


def enqueue_reindex(model: str) -> dict[str, int]:
    """임베딩 모델을 바꾼다: reindex_jobs 한 줄을 바로 만들고 {job_id, total(조각 수)}. 시작할 수 없으면 ReindexRefused."""
    store = vectors.STORE
    if store is None or not store.available():
        raise ReindexRefused("뜻 검색 저장소(Qdrant)에 연결할 수 없습니다.")
    with _db() as session:
        if _running(session) is not None:
            raise ReindexRefused("이미 다시 넣는 중입니다.")
        total, top = _span(session)
        job = ReindexJob(model=model, collection="", total=total)
        session.add(job)
        session.commit()
        with _lock:
            _cursors[job.id] = (0, top)
        _push(_Item("reindex", job.id))
        return {"job_id": job.id, "total": total}


def reload() -> None:
    """서버가 뜰 때: DB 에 남은 일을 작업 줄에 다시 넣는다(extracted 파일, running 다시 넣기 — 처음부터)."""
    with _db() as session:
        for file_id in session.scalars(select(FileRow.id).where(FileRow.status == "extracted").order_by(FileRow.id)):
            _push(_Item("file", file_id))
        total, top = _span(session)
        for job in session.scalars(select(ReindexJob).where(ReindexJob.status == "running").order_by(ReindexJob.id)):
            job.total, job.done = total, 0
            with _lock:
                _cursors[job.id] = (0, top)
            _push(_Item("reindex", job.id))
        session.commit()


def forget(file_id: int) -> None:
    """완전히 지운 파일: 줄에서 빼고 Qdrant 점도 지운다(안 되면 경고만 — 검색은 없는 조각을 버린다)."""
    with _lock:
        _queue[:] = [i for i in _queue if not (i.kind == "file" and i.id == file_id)]
        _waiting.discard(file_id)
    store = vectors.STORE
    if store is None:
        return
    try:
        store.delete_file(file_id)
    except Exception as exc:  # noqa: BLE001 — 지우기는 끝까지 가고 종류만 남긴다
        logger.warning("Qdrant 점 지우기 실패: 파일 %d (%s)", file_id, type(exc).__name__)


async def _store_vectors(session: Session, store: vectors.Store, model: str, pieces: list) -> str:
    """pieces [(조각 id, 파일 id, 글)] 를 model 로 임베딩해 그 모델 컬렉션에 넣고 컬렉션 이름을 돌려준다."""
    found = await embed(session, [text for _, _, text in pieces], model=model)
    collection = vectors.collection_for(model, len(found[0]))
    points = [vectors.Point(chunk_id, file_id, v) for (chunk_id, file_id, _), v in zip(pieces, found, strict=True)]
    await asyncio.to_thread(store.upsert, collection, points)
    return collection


async def _index_file(file_id: int) -> None:
    store = vectors.STORE
    with _db() as session:
        row = session.get(FileRow, file_id)
        if store is None or row is None or row.status != "extracted":
            return  # 뜻 검색 끔 · 지운 파일 · 이미 넣음
        query = select(FileChunk.id, FileChunk.file_id, FileChunk.text).where(FileChunk.file_id == file_id)
        pieces = list(session.execute(query.order_by(FileChunk.seq)).all())
        if pieces:
            if not await asyncio.to_thread(store.available):
                raise _QdrantDown
            job, model = _running(session), active_model(session)
            await _store_vectors(session, store, model, pieces)
            if job is not None and job.model != model:  # 다시 넣기 중이면 새 컬렉션에도
                job.collection = await _store_vectors(session, store, job.model, pieces)
        row.status = "indexed"
        if row.reason == NOT_READY:
            row.reason = None
        session.commit()


async def _reindex_step(job_id: int) -> None:
    store = vectors.STORE
    with _db() as session:
        job = session.get(ReindexJob, job_id)
        if job is None or job.status != "running":
            return
        with _lock:
            cursor = _cursors.get(job_id)
        after, top = cursor if cursor is not None else (0, _span(session)[1])
        query = select(FileChunk.id, FileChunk.file_id, FileChunk.text).where(FileChunk.id > after, FileChunk.id <= top)
        pieces = list(session.execute(query.order_by(FileChunk.id).limit(BATCH)).all())
        if not pieces:
            await _finish(session, store, job)
            return
        job.collection = await _store_vectors(session, store, job.model, pieces)
        job.done += len(pieces)
        session.commit()
        with _lock:
            _cursors[job_id] = (pieces[-1][0], top)
    _push(_Item("reindex", job_id))  # 줄 끝으로 — 그 사이 들어온 파일 작업이 먼저


async def _finish(session: Session, store: vectors.Store, job: ReindexJob) -> None:
    """바꾼다(done) → 옛 컬렉션을 지운다. 지우지 못하면 경고만(다음 바꾸기 때 지운다)."""
    job.status, job.finished_at = "done", datetime.now(UTC)
    keep = job.collection
    session.commit()
    with _lock:
        _cursors.pop(job.id, None)
    try:
        for name in await asyncio.to_thread(store.collections):
            if name != keep:
                await asyncio.to_thread(store.drop, name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("옛 컬렉션 지우기 실패 (%s)", type(exc).__name__)


def _note_not_ready(file_id: int) -> None:
    with _db() as session:
        row = session.get(FileRow, file_id)
        if row is not None and row.status == "extracted" and row.reason is None:
            row.reason = NOT_READY
            session.commit()


def _give_up(job_id: int) -> None:
    with _db() as session:
        job = session.get(ReindexJob, job_id)
        if job is not None and job.status == "running":
            job.status, job.finished_at = "failed", datetime.now(UTC)
            session.commit()
    with _lock:
        _cursors.pop(job_id, None)


def _failed(item: _Item, exc: Exception) -> None:
    """다시 할 차례에 넣거나(RETRY_S 뒤), 다 썼으면 파일은 「다시 넣기」 줄로·다시 넣기는 failed."""
    code = exc.code if isinstance(exc, EmbedFailed) else type(exc).__name__
    logger.warning("뒤 작업 실패: %s %d (%s, %d번째)", item.kind, item.id, code, item.retries + 1)
    if item.kind == "file":
        _note_not_ready(item.id)
    if item.retries < MAX_RETRIES:
        item.retries, item.not_before = item.retries + 1, time.monotonic() + RETRY_S
        with _lock:
            _queue.append(item)
    elif item.kind == "file":
        with _lock:
            _waiting.add(item.id)
    else:
        _give_up(item.id)


async def _do(item: _Item) -> None:
    try:
        if item.kind == "file":
            await _index_file(item.id)
        else:
            await _reindex_step(item.id)
    except _QdrantDown:
        logger.warning("Qdrant 를 쓸 수 없어 다시 넣기 줄에 둡니다: 파일 %d", item.id)
        _note_not_ready(item.id)
        with _lock:
            _waiting.add(item.id)
    except Exception as exc:  # noqa: BLE001 — 일꾼은 멈추지 않는다. 종류·code 만 남긴다(키가 담길 수 있는 글은 남기지 않는다)
        _failed(item, exc)


def _take() -> _Item | None:
    now = time.monotonic()
    with _lock:
        for i, item in enumerate(_queue):
            if item.not_before <= now:
                return _queue.pop(i)
    return None


async def drain() -> None:
    """지금 할 수 있는 작업을 차례로 모두 한다. 나중에 다시 할 작업은 줄에 남긴다."""
    while (item := _take()) is not None:
        await _do(item)


async def recheck() -> int:
    """「다시 넣기」 줄: Qdrant 가 되면 모두 작업 줄로 옮긴다. 옮긴 파일 수."""
    store = vectors.STORE
    with _lock:
        ids = sorted(_waiting)
    if not ids or store is None or not await asyncio.to_thread(store.available):
        return 0
    for file_id in ids:
        _push(_Item("file", file_id))
    return len(ids)


def _pause() -> float:
    """다음 다시 할 작업까지(없으면 RECHECK_S), 길어야 RECHECK_S."""
    with _lock:
        soonest = min((item.not_before for item in _queue), default=None)
    gap = RECHECK_S if soonest is None else soonest - time.monotonic()
    return max(0.0, min(gap, RECHECK_S))


async def _run(wake: asyncio.Event) -> None:
    checked = time.monotonic()
    while True:
        wake.clear()  # 비우기 전에 — 하는 동안 들어온 작업이 깨운 것을 잃지 않게
        try:
            await drain()
            if time.monotonic() - checked >= RECHECK_S:
                checked = time.monotonic()
                await recheck()
        except Exception as exc:  # noqa: BLE001 — 실패 처리마저 깨져도(DB 잠김 등) 일꾼은 멈추지 않는다. 그 파일은 다음 시작 때 다시
            logger.warning("뒤 작업 일꾼 오류 (%s)", type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(wake.wait(), timeout=_pause())


def start() -> None:
    """서버가 뜰 때(lifespan, 이벤트 루프 안). CHRONOS_QDRANT_URL 이 빈 값이면 뜻 검색을 끄고 아무것도 하지 않는다."""
    global _loop, _wake, _task
    url = Settings().qdrant_url
    if not url:
        return
    vectors.STORE = vectors.Store(url)
    _loop, _wake = asyncio.get_running_loop(), asyncio.Event()
    reload()
    _task = asyncio.create_task(_run(_wake))


async def stop() -> None:
    global _loop, _wake, _task
    task, _task, _loop, _wake = _task, None, None, None
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
