"""저장된 근거 다시 쓰기(설계 2026-11-23): evidence.search 가 Liner 를 부르기 전에 먼저 찾아보는 곳.

- 다시 쓸 수 있는 근거(코드가 정한다): 찾은 mode 가 REUSE_MODES 가운데 하나이고(부른 mode 와 달라도 된다 — 근거마다
  제 mode 를 알린다), 붙은 곳(evidence_links)이 하나 이상 있고, 찾은 지 REUSE_DAYS×24시간 안이고, 「다시 쓰지 않기」
  (retired)가 아닌 근거. 회사 전체가 함께 쓴다(대화·일정을 가리지 않는다). 기간이 지나도 지우지 않는다.
  맞는지의 판단은 에이전트가 한다(그때의 검색어 found_by 도 함께 준다).
- 찾는 법: 낱말 맞추기만(뜻 검색 없음). 다시 쓸 수 있는 근거는 적으므로(붙은 것·30일 안) 모두 읽어 코드로 맞춘다.
  글 = 제목 + 요약 + 그때의 검색어. 맞는 것은 새것부터.
- 최소 관련도: 물음의 뜻 있는 낱말(두 글자 이상, 세 글자 이상이면 끝 조사 하나를 뗀다)이 MIN_WORDS 개 이상이고
  (모두 두 글자이면 MIN_SHORT_WORDS 개 이상 — 「공사 기간」 같은 흔한 말), 그 낱말이 모두(MIN_SHARE) 근거 글 어느 낱말
  안에 들어 있어야 한다(「철근 콘크리트」→ 철근콘크리트). 숫자가 든 낱말(5층·3일)은 근거 낱말의 앞부분과만 맞춘다
  (15층·13일 에 맞지 않게). 아니면 버린다 — 관계없는 근거를 맞는 근거처럼 내놓지 않게.
- 다시 쓴 호출은 evidence_searches 에 mode REUSE_MODE 줄로 남긴다(검색 수·사용량에 들지 않는다, 요청당 상한을 센다).
- 쓰기는 flush 만 한다(commit 은 부르는 쪽).
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.store.evidence import REUSE_MODE
from app.store.tables import EvidenceItem, EvidenceLink, EvidenceSearch
from app.store.timeutil import as_utc

REUSE_DAYS = 30
REUSE_MODES = ("web", "scholar", "legal", "business")  # 날씨·정보 API 결과는 실시간 값이라 다시 쓰지 않는다
MIN_SHARE = 1.0  # 물음 낱말이 모두 맞아야 한다
MIN_WORDS = 2  # 뜻 있는 낱말이 이보다 적으면(「공기」 하나) 찾지 않는다
SHORT_WORD, MIN_SHORT_WORDS = 2, 3  # 낱말이 모두 두 글자이면 세 개는 되어야 찾는다(「공사 기간」은 너무 흔하다)
PARTICLES = ("으로", "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도")  # 뗄 끝 조사(긴 것 먼저)
MIN_WORD = 2  # 글자. 한 글자 낱말(및·등)은 관련도에 넣지 않는다
MAX_QUERY_WORDS = 20
SEOUL = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class Saved:
    item: EvidenceItem
    mode: str  # 그 근거를 찾은 mode(web·scholar·legal·business)
    found_by: str  # 그때의 검색어
    searched_at: str  # 찾은 날(서울, ISO 날짜)
    age_days: int  # 서울 날짜로 센 지난 날 수


def _words(value: str) -> list[str]:
    return re.findall(r"\w+", value.lower())


def _bare(word: str) -> str:
    """세 글자 이상 낱말의 끝 조사 하나를 뗀다(남는 것이 두 글자 이상일 때만). 「착공신고의」→「착공신고」."""
    if len(word) >= 3:
        for particle in PARTICLES:
            if word.endswith(particle) and len(word) - len(particle) >= 2:
                return word[: -len(particle)]
    return word


def _share(words: list[str], body: str) -> float:
    """물음 낱말 가운데 근거 글 어느 낱말 안에 들어 있는 것의 몫. 숫자가 든 낱말은 근거 낱말의 앞부분과만 맞춘다."""
    found = _words(body)

    def hit(q: str) -> bool:
        if any(c.isdigit() for c in q):
            return any(w.startswith(q) for w in found)
        return any(q in w for w in found)

    return sum(hit(q) for q in words) / len(words)


def searched_at(item: EvidenceItem) -> str:
    return as_utc(item.created_at).astimezone(SEOUL).date().isoformat()


def age_days(item: EvidenceItem, now: datetime) -> int:
    """searched_at 과 같은 서울 날짜로 센다(오늘 찾았으면 0)."""
    return (now.astimezone(SEOUL).date() - as_utc(item.created_at).astimezone(SEOUL).date()).days


def find(session: Session, query: str, limit: int, now: datetime | None = None) -> list[Saved]:
    """다시 쓸 수 있는 근거 가운데 최소 관련도를 넘는 것, 잘 맞는 차례(같으면 새것부터)로 limit 개까지. 없으면 []."""
    words = list(dict.fromkeys(_bare(w) for w in _words(query) if len(w) >= MIN_WORD))[:MAX_QUERY_WORDS]
    if len(words) < MIN_WORDS or (all(len(w) == SHORT_WORD for w in words) and len(words) < MIN_SHORT_WORDS):
        return []
    now = now or datetime.now(UTC)
    since = (now - timedelta(days=REUSE_DAYS)).replace(tzinfo=None)  # DB 는 시간대 없는 UTC
    linked = select(EvidenceLink.id).where(EvidenceLink.evidence_id == EvidenceItem.id).exists()
    statement = (
        select(EvidenceItem, EvidenceSearch.mode, EvidenceSearch.query)
        .join(EvidenceSearch, EvidenceSearch.id == EvidenceItem.search_id)
        .where(EvidenceSearch.mode.in_(REUSE_MODES), linked, EvidenceItem.created_at >= since,
               EvidenceItem.retired.is_(False))
        .order_by(EvidenceItem.created_at.desc(), EvidenceItem.id.desc())
    )
    scored = [(share, item, mode, found_by) for item, mode, found_by in session.execute(statement)
              if (share := _share(words, f"{item.title} {item.description} {found_by}")) >= MIN_SHARE]
    scored.sort(key=lambda s: -s[0])  # 같은 몫은 새것부터 그대로
    return [Saved(item, mode, found_by, searched_at(item), age_days(item, now))
            for _, item, mode, found_by in scored[:limit]]


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
