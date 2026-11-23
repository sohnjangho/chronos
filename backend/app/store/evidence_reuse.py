"""저장된 근거 다시 쓰기(설계 2026-11-23): evidence.search 가 Liner 를 부르기 전에 먼저 찾아보는 곳.

- 다시 쓸 수 있는 근거(코드가 정한다): 찾은 mode 가 REUSE_MODES 가운데 부른 mode 와 같고, 붙은 곳(evidence_links)이
  하나 이상 있고, 찾은 지 REUSE_DAYS 날 안이고, 「다시 쓰지 않기」(retired)가 아닌 근거. 회사 전체가 함께 쓴다
  (대화·일정을 가리지 않는다). 기간이 지나도 지우지 않는다. 맞는지의 판단은 에이전트가 한다.
- 찾는 법: 낱말 검색만(FTS5 표 evidence_items_fts — 제목·요약·그때의 검색어, app.store.tables). 파일 낱말 검색처럼
  기본 토크나이저에 낱말 앞부분 맞추기("골조"* — 골조의·골조공사). 뜻 검색(Qdrant)은 없다.
- 최소 관련도: 물음의 뜻 있는 낱말(두 글자 이상) 가운데 MIN_SHARE 몫 이상이 근거 글 낱말의 앞부분과 맞아야 한다
  (낱말이 둘이면 둘 다, 셋이면 둘, 넷이면 셋). 낮으면 버린다 — 관계없는 근거를 내놓지 않게(실측 없음, 보수적으로).
- 다시 쓴 호출은 evidence_searches 에 mode REUSE_MODE 줄로 남긴다(검색 수·사용량에 들지 않는다, 요청당 상한을 센다).
- 쓰기는 flush 만 한다(commit 은 부르는 쪽).
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import Session

from app.store.evidence import REUSE_MODE
from app.store.tables import EvidenceItem, EvidenceLink, EvidenceSearch
from app.store.timeutil import as_utc

REUSE_DAYS = 30
REUSE_MODES = ("web", "scholar", "legal", "business")  # 날씨·정보 API 결과는 실시간 값이라 다시 쓰지 않는다
MIN_SHARE = 0.6
MIN_WORD = 2  # 글자. 한 글자 낱말(및·등)은 관련도에 넣지 않는다
MAX_QUERY_WORDS = 20
SEOUL = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class Saved:
    item: EvidenceItem
    searched_at: str  # 찾은 날(서울, ISO 날짜)
    age_days: int


def _words(value: str) -> list[str]:
    return re.findall(r"\w+", value.lower())


def _share(words: list[str], body: str) -> float:
    """물음 낱말 가운데 근거 글 낱말의 앞부분과 맞는 몫."""
    found = _words(body)
    return sum(any(w.startswith(q) for w in found) for q in words) / len(words)


def searched_at(item: EvidenceItem) -> str:
    return as_utc(item.created_at).astimezone(SEOUL).date().isoformat()


def age_days(item: EvidenceItem, now: datetime) -> int:
    return (now - as_utc(item.created_at)).days


def _reusable(mode: str, now: datetime):
    since = (now - timedelta(days=REUSE_DAYS)).replace(tzinfo=None)  # DB 는 시간대 없는 UTC
    linked = select(EvidenceLink.id).where(EvidenceLink.evidence_id == EvidenceItem.id).exists()
    return (
        select(EvidenceItem)
        .join(EvidenceSearch, EvidenceSearch.id == EvidenceItem.search_id)
        .where(EvidenceSearch.mode == mode, EvidenceSearch.mode.in_(REUSE_MODES), linked,
               EvidenceItem.created_at >= since, EvidenceItem.retired.is_(False))
    )


def find(session: Session, query: str, mode: str, limit: int, now: datetime | None = None) -> list[Saved]:
    """다시 쓸 수 있는 근거 가운데 최소 관련도를 넘는 것, 잘 맞는 차례로 limit 개까지(같으면 bm25 차례). 없으면 []."""
    words = list(dict.fromkeys(w for w in _words(query) if len(w) >= MIN_WORD))[:MAX_QUERY_WORDS]
    if not words:
        return []
    now = now or datetime.now(UTC)
    items = {i.id: i for i in session.scalars(_reusable(mode, now))}  # 다시 쓸 수 있는 것(붙은 것·30일 안이라 적다)
    if not items:
        return []
    statement = text("SELECT rowid, text FROM evidence_items_fts WHERE evidence_items_fts MATCH :m AND rowid IN :ids "
                     "ORDER BY bm25(evidence_items_fts)").bindparams(bindparam("ids", expanding=True))
    rows = session.execute(statement, {"m": " OR ".join(f'"{w}"*' for w in words), "ids": list(items)}).all()
    scored = [(share, rank, items[rowid]) for rank, (rowid, body) in enumerate(rows)
              if (share := _share(words, body)) >= MIN_SHARE]
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [Saved(i, searched_at(i), age_days(i, now)) for _, _, i in scored[:limit]]


def record_reuse(session: Session, *, chat_session_id: int | None, query: str, result_count: int, latency_ms: int) -> int:
    """다시 쓴 호출 한 줄(mode REUSE_MODE)을 넣고 flush 한다. 그 줄의 id."""
    row = EvidenceSearch(chat_session_id=chat_session_id, query=query, mode=REUSE_MODE, ok=True,
                         result_count=result_count, latency_ms=latency_ms)
    session.add(row)
    session.flush()
    return row.id


def reuses_since(session: Session, chat_session_id: int, since: datetime | None) -> int:
    """그 대화에서 since 뒤(같은 때 포함)에 다시 쓴 수. since 가 None 이면 그 대화의 모든 다시 쓰기."""
    query = select(func.count()).select_from(EvidenceSearch).where(
        EvidenceSearch.chat_session_id == chat_session_id, EvidenceSearch.mode == REUSE_MODE)
    if since is not None:
        query = query.where(EvidenceSearch.created_at >= since)
    return session.scalar(query) or 0


def set_retired(session: Session, evidence_id: int, retired: bool) -> bool:
    """「다시 쓰지 않기」를 켜거나 끄고 flush 한다. 없는 근거면 False."""
    item = session.get(EvidenceItem, evidence_id)
    if item is None:
        return False
    item.retired = retired
    session.flush()
    return True
