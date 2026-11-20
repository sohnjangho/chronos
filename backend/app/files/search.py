"""뜻+낱말 검색: 뜻(Qdrant)과 낱말(FTS5, store.files.keyword_search)을 RRF(k=60)로 합친다.

- 뜻 쪽은 jobs.active_model(다시 넣기 중이면 옛 모델)로 물음을 임베딩해 그 모델 컬렉션에서 찾는다. 점수(코사인)가
  MIN_SCORE 보다 낮은 조각은 버린다. 뜻 검색을 껐거나 물음 임베딩(QUERY_TIMEOUT_S)·Qdrant 찾기가 실패하면 낱말 쪽만.
- filters = {축: [값…]}: 축마다 값 가운데 하나를 가진 파일, 축끼리는 모두(AND). 빈 목록인 축은 거르지 않는다.
- file_ids(한 파일 안에서 찾기 등)를 주면 그 파일들 안에서만 — filters 와 함께면 둘 다 맞는 파일.
- prefer_file_ids(지금 대화에 붙인 파일)의 조각은 점수 ×PREFER. 숨긴(지운) 파일의 조각은 나오지 않는다.
- 받은 세션은 읽기만 한다.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.files import jobs, vectors
from app.llm.embeddings import EmbedFailed, embed
from app.store import files
from app.store.tables import FileAxis, FileChunk, FileRow

logger = logging.getLogger(__name__)

RRF_K = 60
PREFER = 1.5
MIN_SCORE = 0.2  # 코사인. 실측 없음 — 뜻이 먼 조각이 RRF 순위만으로 올라오지 않게(PM 조정 대상)
POOL = 4  # 양쪽에서 limit × POOL 개까지 본다
QUERY_TIMEOUT_S = 10.0  # 물음 임베딩 — 늦으면 낱말 쪽만

Source = Literal["vector", "keyword", "both"]


@dataclass(frozen=True)
class Hit:
    file_id: int
    chunk_id: int
    locator: str
    text: str
    score: float  # RRF 점수(붙인 파일은 ×PREFER). 클수록 잘 맞는다
    source: Source


def _filtered(session: Session, filters: dict[str, list[str]] | None) -> list[int] | None:
    """축 거르기를 파일 id 로. 거를 것이 없으면 None."""
    ids: set[int] | None = None
    for axis, values in (filters or {}).items():
        if not values:
            continue
        found = set(session.scalars(select(FileAxis.file_id).where(FileAxis.axis == axis, FileAxis.value.in_(values))))
        ids = found if ids is None else ids & found
    return None if ids is None else sorted(ids)


def _visible(session: Session, chunk_ids: list[int]) -> dict[int, FileChunk]:
    query = (
        select(FileChunk)
        .join(FileRow, FileRow.id == FileChunk.file_id)
        .where(FileChunk.id.in_(chunk_ids), FileRow.deleted_at.is_(None))
    )
    return {c.id: c for c in session.scalars(query)}


async def _meaning(session: Session, query: str, pool: int, file_ids: list[int] | None) -> list[FileChunk]:
    """뜻 쪽 조각(점수 큰 차례). 쓸 수 없으면 []."""
    store = vectors.STORE
    if store is None:
        return []
    model = jobs.active_model(session)
    try:
        [vector] = await embed(session, [query], model=model, timeout_s=QUERY_TIMEOUT_S)
        found = await asyncio.to_thread(store.search, store.collection_for(model, len(vector)), vector, pool,
                                        None if file_ids is None else {"file_id": file_ids})
    except EmbedFailed:
        return []
    except Exception as exc:  # noqa: BLE001 — Qdrant 가 찾는 사이 끊겼다: 낱말 쪽만
        logger.warning("뜻 검색 실패 (%s)", type(exc).__name__)
        return []
    order = [chunk_id for chunk_id, score in found if score >= MIN_SCORE]
    rows = _visible(session, order)
    return [rows[chunk_id] for chunk_id in order if chunk_id in rows]


def _fuse(keyword: list[files.ChunkHit], meaning: list[FileChunk], limit: int, prefer: set[int]) -> list[Hit]:
    scores: dict[int, float] = {}
    sources: dict[int, set[str]] = {}
    info: dict[int, tuple[int, str, str]] = {}
    ranked = [(h.chunk_id, h.file_id, h.locator, h.text, "keyword") for h in keyword]
    ranked += [(c.id, c.file_id, c.locator, c.text, "vector") for c in meaning]
    ranks = {"keyword": 0, "vector": 0}
    for chunk_id, file_id, locator, text, source in ranked:
        ranks[source] += 1
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (RRF_K + ranks[source])
        sources.setdefault(chunk_id, set()).add(source)
        info.setdefault(chunk_id, (file_id, locator, text))
    hits = []
    for chunk_id, score in scores.items():
        file_id, locator, text = info[chunk_id]
        source = "both" if len(sources[chunk_id]) == 2 else next(iter(sources[chunk_id]))
        hits.append(Hit(file_id, chunk_id, locator, text, score * (PREFER if file_id in prefer else 1), source))
    hits.sort(key=lambda h: -h.score)  # 같은 점수는 낱말 쪽 차례 그대로
    return hits[:limit]


async def search(
    session: Session,
    query: str,
    *,
    limit: int = 8,
    filters: dict[str, list[str]] | None = None,
    prefer_file_ids: list[int] | None = None,
    file_ids: list[int] | None = None,
) -> list[Hit]:
    """숨기지 않은 파일의 조각을 뜻+낱말로 찾는다(점수 큰 차례로 limit 개까지).

    file_ids 를 주면 그 파일들 안에서만(filters 와 함께면 둘 다 맞는 파일).
    """
    allowed = _filtered(session, filters)
    if file_ids is not None:
        allowed = sorted(set(file_ids) if allowed is None else set(file_ids) & set(allowed))
    if allowed == [] or not query.strip():
        return []
    pool = limit * POOL
    keyword = files.keyword_search(session, query, pool, allowed)
    meaning = await _meaning(session, query, pool, allowed)
    return _fuse(keyword, meaning, limit, set(prefer_file_ids or ()))
