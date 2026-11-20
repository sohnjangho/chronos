"""파일 뒤 작업 줄: 글 조각을 임베딩해 뜻 검색(Qdrant)에 넣기 · 임베딩 모델 바꾸기(다시 넣기).

- 줄은 메모리에 있고 일꾼 하나가 하나씩 차례로 한다(서버가 뜰 때 start, 닫을 때 stop). 서버가 다시 뜨면 DB 에서 다시 읽는다
  (reload): status extracted 인 파일 · status running 인 다시 넣기(처음부터 — 같은 조각은 바꿔 넣을 뿐이다).
- 파일 하나: 조각을 지금 모델(active_model)로 임베딩해 그 컬렉션에 넣고 status indexed. 다시 넣기 중이면 새 모델 컬렉션에도
  넣는다(두 컬렉션 모두). 조각이 없는 파일은 임베딩 없이 indexed.
- 실패하면 status extracted + reason 「뜻 검색 준비 안 됨」(다른 까닭이 이미 있으면 그대로)이고 RETRY_S 뒤 다시(MAX_RETRIES 번).
  다시 해도 나아지지 않는 실패(GIVE_UP_CODES — 키·크레딧·연결·요청 모양)는 다시 하지 않는다. 다 썼거나 Qdrant 가 안 되면
  「다시 넣기」 줄(waiting)에 남는다. RECHECK_S 마다 Qdrant 가 되면 작업 줄로 옮기고, 거기서 꺼낸 것은 한 번만 해 본다.
- 다시 넣기(enqueue_reindex): reindex_jobs 한 줄을 바로 만든다. 시작 때 가장 큰 조각 id 까지를 BATCH 개씩 새 모델로 새
  컬렉션에 넣는다 — 한 걸음마다 줄 끝으로 돌아가므로 그 사이 들어온 파일 작업이 먼저 돈다. 다 넣으면 done → 검색이 새 모델·
  새 컬렉션으로 바뀌고 이 인스턴스의 다른 컬렉션은 지운다. 한 걸음이 다시 해도 안 되면 failed(검색은 옛 그대로).
- 지금 모델(active_model) = 마지막으로 끝난(done) 다시 넣기의 모델, 없으면 기본 임베딩 모델. 배정(assignments)은 바꾸기를
  시작할 때 바로 새 모델이 되므로, 검색·파일 넣기는 배정이 아니라 이것을 따른다.
- 파일마다 임베딩을 해 본 뒤(성공·실패·뜻 검색 꺼짐 모두) 분류 단계(files.classify.after_index — 요약이 없을 때 한 번)를
  부른다. 이미 분류된 파일이 뒤에 임베딩되면 indexed 가 아니라 classified. 뜻 검색이 꺼져도 일꾼은 돈다.
- DB 쓰기·읽기 묶음은 asyncio.to_thread 로(이벤트 루프를 SQLite 잠금 기다림에 묶지 않게), 묶음마다 새 세션.
"""

import asyncio
import contextlib
import logging
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.files import classify, merge_suggest, vectors
from app.llm.assignments import DEFAULT_ASSIGNMENTS
from app.llm.embeddings import EmbedFailed, embed
from app.store.tables import FileChunk, FileRow, ReindexJob, Setting

logger = logging.getLogger(__name__)

NOT_READY = "뜻 검색 준비 안 됨"
BATCH = 64  # 다시 넣기 한 걸음의 조각 수
RETRY_S = 30.0
MAX_RETRIES = 3
RECHECK_S = 300.0  # 「다시 넣기」 줄을 볼 간격(5분)
GIVE_UP_CODES = frozenset({"bad_key", "no_credit", "no_connection", "secret_unreadable", "bad_request"})
INSTANCE_KEY = "qdrant_instance"  # settings 표: 이 서버의 Qdrant 컬렉션 앞말


REFUSED = {
    "running": "이미 다시 넣는 중입니다.",
    "down": "뜻 검색 저장소(Qdrant)에 연결할 수 없습니다.",
    "off": "뜻 검색이 꺼져 있습니다(CHRONOS_QDRANT_URL).",
}


class ReindexRefused(Exception):
    """다시 넣기를 시작할 수 없다. code: running(이미 다시 넣는 중) · down(Qdrant 에 연결할 수 없음) · off(뜻 검색 꺼짐)."""

    def __init__(self, code: Literal["running", "down", "off"]) -> None:
        super().__init__(REFUSED[code])
        self.code = code
        self.message = REFUSED[code]


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


def _pieces(session: Session, *where, limit: int | None = None) -> list[tuple[int, int, str]]:
    """[(조각 id, 파일 id, 글)] 조각 id 차례."""
    query = select(FileChunk.id, FileChunk.file_id, FileChunk.text).where(*where).order_by(FileChunk.id).limit(limit)
    return [tuple(row) for row in session.execute(query)]


def enqueue_reindex(model: str) -> dict[str, int]:
    """임베딩 모델을 바꾼다: reindex_jobs 한 줄을 바로 만들고 {job_id, total(조각 수)}. 시작할 수 없으면 ReindexRefused."""
    store = vectors.STORE
    if store is None:
        raise ReindexRefused("off")
    if not store.available():
        raise ReindexRefused("down")
    with _db() as session:
        job = ReindexJob(model=model, collection="", total=0)
        session.add(job)
        # 쓰기 잠금을 먼저 잡는다: 둘이 동시에 시작하지 않고, 센 뒤에 들어온 조각은 그 파일 작업이 두 컬렉션에 넣는다.
        session.flush()
        if session.scalar(select(ReindexJob.id).where(ReindexJob.status == "running", ReindexJob.id != job.id)):
            session.rollback()
            raise ReindexRefused("running")
        job.total, top = _span(session)
        session.commit()
        with _lock:
            _cursors[job.id] = (0, top)
        _push(_Item("reindex", job.id))
        return {"job_id": job.id, "total": job.total}


def reload() -> None:
    """서버가 뜰 때: DB 에 남은 일을 작업 줄에 다시 넣는다(extracted·indexed 파일, running 다시 넣기 — 처음부터)."""
    with _db() as session:
        # indexed = 아직 분류 안 됨(분류가 실패했거나 분류 전에 서버가 멈췄다) — 임베딩은 건너뛰고 분류만 다시
        leftover = select(FileRow.id).where(FileRow.status.in_(("extracted", "indexed"))).order_by(FileRow.id)
        for file_id in session.scalars(leftover):
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


async def _store_vectors(store: vectors.Store, model: str, pieces: list[tuple[int, int, str]]) -> str:
    """pieces [(조각 id, 파일 id, 글)] 를 model 로 임베딩해 그 모델 컬렉션에 넣고 컬렉션 이름을 돌려준다."""
    with _db() as session:  # embed 는 배정·연결을 읽기만 한다(기록은 따로 스레드에서)
        found = await embed(session, [text for _, _, text in pieces], model=model)
    collection = store.collection_for(model, len(found[0]))
    points = [vectors.Point(chunk_id, file_id, v) for (chunk_id, file_id, _), v in zip(pieces, found, strict=True)]
    await asyncio.to_thread(store.upsert, collection, points)
    return collection


def _file_work(file_id: int) -> tuple[list[tuple[int, int, str]], str, tuple[int, str] | None] | None:
    """(조각들, 지금 모델, 진행 중 다시 넣기 (id, 모델)). 할 일이 없으면 None(지운 파일·이미 넣음)."""
    with _db() as session:
        row = session.get(FileRow, file_id)
        if row is None or row.status != "extracted":
            return None
        job = _running(session)
        return _pieces(session, FileChunk.file_id == file_id), active_model(session), (job.id, job.model) if job else None


def _mark_indexed(file_id: int, job_id: int | None, collection: str | None) -> None:
    with _db() as session:
        row = session.get(FileRow, file_id)
        if row is not None and row.status == "extracted":
            row.status = "classified" if row.summary else "indexed"  # 뜻 검색보다 먼저 분류됐을 수 있다(Task 49)
            if row.reason == NOT_READY:
                row.reason = classify.BIG_IMAGE if classify.big_image(row) else None
        job = session.get(ReindexJob, job_id) if job_id is not None and collection else None
        if job is not None and job.status == "running":
            job.collection = collection
        session.commit()


async def _index_file(file_id: int) -> None:
    store = vectors.STORE
    work = None if store is None else await asyncio.to_thread(_file_work, file_id)
    if work is None:
        return  # 뜻 검색 끔 · 지운 파일 · 이미 넣음
    pieces, model, job = work
    collection = None
    if pieces:
        if not await asyncio.to_thread(store.available):
            raise _QdrantDown
        await _store_vectors(store, model, pieces)
        if job is not None and job[1] != model:  # 다시 넣기 중이면 새 컬렉션에도
            collection = await _store_vectors(store, job[1], pieces)
    await asyncio.to_thread(_mark_indexed, file_id, job[0] if job else None, collection)


def _step_work(job_id: int) -> tuple[str, list[tuple[int, int, str]], int] | None:
    """(새 모델, 다음 조각들, 시작 때 가장 큰 조각 id). 끝났거나 없는 작업이면 None."""
    with _db() as session:
        job = session.get(ReindexJob, job_id)
        if job is None or job.status != "running":
            return None
        with _lock:
            cursor = _cursors.get(job_id)
        after, top = cursor if cursor is not None else (0, _span(session)[1])
        return job.model, _pieces(session, FileChunk.id > after, FileChunk.id <= top, limit=BATCH), top


def _record_step(job_id: int, collection: str, count: int) -> None:
    with _db() as session:
        job = session.get(ReindexJob, job_id)
        if job is not None and job.status == "running":
            job.collection, job.done = collection, job.done + count
            session.commit()


async def _reindex_step(job_id: int) -> None:
    store = vectors.STORE
    work = await asyncio.to_thread(_step_work, job_id)
    if work is None:
        return
    model, pieces, top = work
    if not pieces:
        await _finish(store, job_id)
        return
    collection = await _store_vectors(store, model, pieces)
    await asyncio.to_thread(_record_step, job_id, collection, len(pieces))
    with _lock:
        _cursors[job_id] = (pieces[-1][0], top)
    _push(_Item("reindex", job_id))  # 줄 끝으로 — 그 사이 들어온 파일 작업이 먼저


def _close_job(job_id: int, status: Literal["done", "failed"]) -> str | None:
    """running 이면 닫고 그 컬렉션 이름을, 아니면 None."""
    with _lock:
        _cursors.pop(job_id, None)
    with _db() as session:
        job = session.get(ReindexJob, job_id)
        if job is None or job.status != "running":
            return None
        job.status, job.finished_at = status, datetime.now(UTC)
        session.commit()
        return job.collection


async def _finish(store: vectors.Store, job_id: int) -> None:
    """바꾼다(done) → 이 인스턴스의 다른 컬렉션을 지운다. 지우지 못하면 경고만(다음 바꾸기 때 지운다)."""
    keep = await asyncio.to_thread(_close_job, job_id, "done")
    if keep is None:
        return
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


async def _quietly(work, *args) -> None:
    """DB 기록(스레드에서). 잠김 등으로 실패해도 줄은 그대로 두고 경고만."""
    try:
        await asyncio.to_thread(work, *args)
    except Exception as exc:  # noqa: BLE001
        logger.warning("뒤 작업 기록 실패 (%s)", type(exc).__name__)


async def _failed(item: _Item, exc: Exception) -> None:
    """줄에 먼저 되돌린다(RETRY_S 뒤 다시 · 다 썼거나 나아지지 않는 실패면 파일은 「다시 넣기」 줄, 다시 넣기는 failed).
    그다음 파일의 「뜻 검색 준비 안 됨」을 남긴다 — 이 기록이 실패해도 줄에서 빠지지 않는다."""
    code = exc.code if isinstance(exc, EmbedFailed) else type(exc).__name__
    logger.warning("뒤 작업 실패: %s %d (%s, %d번째)", item.kind, item.id, code, item.retries + 1)
    if item.retries < MAX_RETRIES and code not in GIVE_UP_CODES:
        item.retries, item.not_before = item.retries + 1, time.monotonic() + RETRY_S
        with _lock:
            _queue.append(item)
    elif item.kind == "file":
        with _lock:
            _waiting.add(item.id)
    else:
        await _quietly(_close_job, item.id, "failed")
    if item.kind == "file":
        await _quietly(_note_not_ready, item.id)


async def _do(item: _Item) -> None:
    try:
        if item.kind == "file":
            try:
                await _index_file(item.id)
            finally:  # 분류는 뜻 검색과 따로(Qdrant 가 꺼졌거나 임베딩이 실패해도). 한 번만 하고 예외를 내지 않는다
                await classify.after_index(item.id)
        else:
            await _reindex_step(item.id)
    except _QdrantDown:
        logger.warning("Qdrant 를 쓸 수 없어 다시 넣기 줄에 둡니다: 파일 %d", item.id)
        with _lock:
            _waiting.add(item.id)
        await _quietly(_note_not_ready, item.id)
    except Exception as exc:  # noqa: BLE001 — 일꾼은 멈추지 않는다. 종류·code 만 남긴다(키가 담길 수 있는 글은 남기지 않는다)
        await _failed(item, exc)


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
    """「다시 넣기」 줄: Qdrant 가 되면 모두 작업 줄로 옮긴다(한 번씩만 해 본다). 옮긴 파일 수."""
    store = vectors.STORE
    with _lock:
        ids = sorted(_waiting)
    if not ids or store is None or not await asyncio.to_thread(store.available):
        return 0
    for file_id in ids:
        _push(_Item("file", file_id, retries=MAX_RETRIES))
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
                await merge_suggest.suggest_if_due()  # 값 합치기 제안(하루 한 번)
        except Exception as exc:  # noqa: BLE001 — 실패 처리마저 깨져도 일꾼은 멈추지 않는다. 그 파일은 다음 시작 때 다시
            logger.warning("뒤 작업 일꾼 오류 (%s)", type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(wake.wait(), timeout=_pause())


def _instance() -> str:
    """이 서버(DB)의 Qdrant 컬렉션 앞말(8자). 처음이면 만들어 settings 에 남기고, 앞말 없이 넣었던(이 고침 전)
    indexed 파일을 extracted 로 되돌려 새 컬렉션에 다시 넣게 한다."""
    with _db() as session:
        row = session.get(Setting, INSTANCE_KEY)
        if row is not None:
            return row.value
        value = secrets.token_hex(4)
        session.add(Setting(key=INSTANCE_KEY, value=value))
        session.execute(update(FileRow).where(FileRow.status == "indexed").values(status="extracted"))
        session.commit()
        return value


def start() -> None:
    """서버가 뜰 때(lifespan, 이벤트 루프 안). 일꾼은 늘 띄운다(분류·합치기 제안은 뜻 검색과 따로). CHRONOS_QDRANT_URL 이
    빈 값이거나 쓸 수 없으면 뜻 검색만 끈다(STORE None, 잘못된 주소는 경고) — 파일은 extracted 로 남고 분류는 된다."""
    global _loop, _wake, _task
    url = Settings().qdrant_url
    if url:
        try:
            vectors.STORE = vectors.Store(url, _instance())
        except Exception as exc:  # noqa: BLE001 — 주소가 잘못돼도 서버는 뜬다(뜻 검색만 끔)
            logger.warning("CHRONOS_QDRANT_URL 을 쓸 수 없어 뜻 검색을 끕니다 (%s)", type(exc).__name__)
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
