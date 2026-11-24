"""근거 보관: 검색 한 번(evidence_searches), 결과 줄(evidence_items), 근거가 받친 곳(evidence_links).

- 링크의 대상은 일정(schedule_id) 또는 초안(draft_id) 하나이고, 받친 것은 조건(condition_id)이나 가정
  (assumption_label)이다. 초안이 승인되어 일정이 되면(ScheduleDraft.schedule_id) 그 초안의 링크도 그 일정의 것이다.
- extra_json 은 scholar 의 authors·journal·citation_count 처럼 검색 방식마다 다른 값을 둔다(없으면 {}).
- 근거 검색 결과는 같은 주소(url)의 살아 있는 줄(「다시 쓰지 않기」가 아니고 SAME_URL_DAYS 안)이 있으면 새로 넣지 않고
  그 줄(그 evidence_id)을 돌려준다. 한 검색 안의 같은 주소도 한 줄. 날씨·정보 API 줄은 같은 주소여도 값이 달라 늘 넣는다.
- 쓰기는 flush 만 한다(commit 은 부르는 쪽).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.store.chats import messages
from app.store.tables import EvidenceItem, EvidenceLink, EvidenceSearch, ScheduleDraft

if TYPE_CHECKING:
    from app.llm.search import SearchHit

WEATHER_MODE = "weather"  # info.weather 가 남기는 줄(근거 검색 한도와 따로 센다)
INFO_MODE = "info"  # info.call 이 남기는 줄(근거 검색·날씨 한도와 따로 센다)
REUSE_MODE = "reuse"  # evidence.search 가 저장된 근거를 다시 쓴 줄(Liner 를 부르지 않았다. app.store.evidence_reuse)
# 관리 포인트 겨냥 검색(app.points.risk)의 자재·환율(Premium Data)·업체(MCP) 줄. 30일 같은 주소 규칙 대신 recent(설정 시간)로 다시 쓴다
KNOWLEDGE_MODE = "knowledge"
NOT_SEARCH_MODES = (WEATHER_MODE, INFO_MODE, REUSE_MODE, KNOWLEDGE_MODE)  # 근거 검색 수에 들지 않는 줄
SAME_URL_DAYS = 30  # 같은 주소의 줄을 다시 돌려주는 기간(evidence_reuse.REUSE_DAYS 와 같다)


@dataclass(frozen=True)
class Found:
    """근거 한 줄과 그 검색, 그리고 (보는 범위 안의) 링크들."""

    item: EvidenceItem
    search: EvidenceSearch
    links: list[EvidenceLink]


def _extra(hit: "SearchHit") -> dict:
    extra: dict = {}
    if hit.authors:
        extra["authors"] = list(hit.authors)
    if hit.journal is not None:
        extra["journal"] = hit.journal
    if hit.citation_count is not None:
        extra["citation_count"] = hit.citation_count
    return extra


def record_search(
    session: Session,
    *,
    chat_session_id: int | None,
    query: str,
    mode: str,
    ok: bool,
    error_code: str | None,
    latency_ms: int,
    hits: Sequence["SearchHit"],
) -> tuple[int, list[EvidenceItem]]:
    """검색 한 줄과 결과 줄들을 넣고 flush 한다. (검색 id, 결과 줄 — 받은 차례 그대로, 같은 주소는 한 줄).

    근거 검색(mode 가 NOT_SEARCH_MODES 가 아님)이면 같은 주소의 살아 있는 줄을 새로 넣지 않고 그대로 돌려준다."""
    row = EvidenceSearch(chat_session_id=chat_session_id, query=query, mode=mode, ok=ok, error_code=error_code,
                         result_count=len(hits), latency_ms=latency_ms)
    session.add(row)
    session.flush()
    if mode in NOT_SEARCH_MODES:
        items = [_item(row.id, h) for h in hits]
        session.add_all(items)
        session.flush()
        return row.id, items
    by_url = _live_by_url(session, {h.url for h in hits})
    items = []
    for h in hits:
        if h.url not in by_url:
            by_url[h.url] = _item(row.id, h)
            session.add(by_url[h.url])
        if by_url[h.url] not in items:
            items.append(by_url[h.url])
    session.flush()
    return row.id, items


def _item(search_id: int, h: "SearchHit") -> EvidenceItem:
    return EvidenceItem(search_id=search_id, title=h.title, url=h.url, hostname=h.hostname, description=h.description,
                        published=h.date, extra_json=_extra(h))


def _live_by_url(session: Session, urls: set[str]) -> dict[str, EvidenceItem]:
    """주소 → 그 주소의 살아 있는 근거 검색 줄(다시 쓰지 않기가 아니고 SAME_URL_DAYS 안, 가장 새것)."""
    if not urls:
        return {}
    since = (datetime.now(UTC) - timedelta(days=SAME_URL_DAYS)).replace(tzinfo=None)  # DB 는 시간대 없는 UTC
    rows = session.scalars(
        select(EvidenceItem).join(EvidenceSearch, EvidenceSearch.id == EvidenceItem.search_id)
        .where(EvidenceItem.url.in_(urls), EvidenceItem.retired.is_(False), EvidenceItem.created_at >= since,
               EvidenceSearch.mode.notin_(NOT_SEARCH_MODES))
        .order_by(EvidenceItem.id.desc())
    )
    found: dict[str, EvidenceItem] = {}
    for item in rows:
        found.setdefault(item.url, item)
    return found


def recent(session: Session, *, mode: str, query: str, hours: int) -> list[EvidenceItem] | None:
    """같은 mode·query 로 hours 시간 안에 성공한 가장 새 검색의 결과 줄(id 차례, 결과가 없었으면 []). 없으면 None.

    관리 포인트 겨냥 검색이 낡은 예보·값을 다시 쓰지 않게 짧은 시간(points_forecast_reuse_hours)만 본다."""
    since = (datetime.now(UTC) - timedelta(hours=hours)).replace(tzinfo=None)  # DB 는 시간대 없는 UTC
    found = session.scalars(
        select(EvidenceSearch.id).where(EvidenceSearch.mode == mode, EvidenceSearch.query == query,
                                        EvidenceSearch.ok.is_(True), EvidenceSearch.created_at >= since)
        .order_by(EvidenceSearch.id.desc())
    ).first()
    if found is None:
        return None
    return list(session.scalars(select(EvidenceItem).where(EvidenceItem.search_id == found).order_by(EvidenceItem.id)))


def last_user_message_at(session: Session, chat_session_id: int) -> datetime | None:
    """그 대화의 마지막 사용자 메시지(새 요청)의 시각. 없으면 None."""
    found = [m.created_at for m in messages(session, chat_session_id) if m.role == "user"]
    return found[-1] if found else None


def searches_since(session: Session, chat_session_id: int, since: datetime | None, *, weather: bool = False,
                   info: bool = False) -> int:
    """그 대화에서 since 뒤(같은 때 포함)에 한 검색 수(실패 포함). since 가 None 이면 그 대화의 모든 검색.

    날씨 조회(mode WEATHER_MODE, info.weather)와 정보 API 조회(mode INFO_MODE, info.call)는 근거 검색과 따로 센다:
    weather=True 면 날씨 조회만, info=True 면 정보 API 조회만, 아니면 둘을 뺀 근거 검색만.
    """
    if weather:
        mode = EvidenceSearch.mode == WEATHER_MODE
    elif info:
        mode = EvidenceSearch.mode == INFO_MODE
    else:
        mode = EvidenceSearch.mode.notin_(NOT_SEARCH_MODES)
    query = select(func.count()).select_from(EvidenceSearch).where(EvidenceSearch.chat_session_id == chat_session_id,
                                                                    mode)
    if since is not None:
        query = query.where(EvidenceSearch.created_at >= since)
    return session.scalar(query) or 0


def existing_ids(session: Session, evidence_ids: Iterable[int]) -> set[int]:
    wanted = set(evidence_ids)
    if not wanted:
        return set()
    return set(session.scalars(select(EvidenceItem.id).where(EvidenceItem.id.in_(wanted))))


def _same(column, value):
    return column.is_(None) if value is None else column == value


def link(
    session: Session,
    *,
    evidence_ids: Sequence[int],
    schedule_id: int | None = None,
    draft_id: int | None = None,
    condition_id: str | None = None,
    assumption_label: str | None = None,
) -> int:
    """근거마다 링크 한 줄을 넣고 flush 한다. 똑같은 링크가 이미 있으면 넣지 않는다. 돌려주는 것은 새로 넣은 수."""
    target = {"schedule_id": schedule_id, "draft_id": draft_id, "condition_id": condition_id,
              "assumption_label": assumption_label}
    added = 0
    for evidence_id in dict.fromkeys(evidence_ids):
        same = select(EvidenceLink.id).where(
            EvidenceLink.evidence_id == evidence_id,
            *(_same(getattr(EvidenceLink, name), value) for name, value in target.items()),
        )
        if session.scalar(same) is not None:
            continue
        session.add(EvidenceLink(evidence_id=evidence_id, **target))
        session.flush()
        added += 1
    return added


def _schedule_links(session: Session, schedule_id: int) -> list[EvidenceLink]:
    """일정의 링크 + 그 일정을 만든 초안의 링크(id 차례)."""
    drafts = select(ScheduleDraft.id).where(ScheduleDraft.schedule_id == schedule_id)
    query = select(EvidenceLink).where(
        or_(EvidenceLink.schedule_id == schedule_id, EvidenceLink.draft_id.in_(drafts))
    ).order_by(EvidenceLink.id)
    return list(session.scalars(query))


def _found(session: Session, item_ids: Iterable[int], links: list[EvidenceLink]) -> list[Found]:
    """근거 id 차례로 Found. links 는 근거마다 나눠 붙인다."""
    ids = sorted(set(item_ids))
    items = session.scalars(select(EvidenceItem).where(EvidenceItem.id.in_(ids)).order_by(EvidenceItem.id)).all()
    searches = {s.id: s for s in session.scalars(
        select(EvidenceSearch).where(EvidenceSearch.id.in_({i.search_id for i in items})))}
    return [Found(i, searches[i.search_id], [x for x in links if x.evidence_id == i.id])
            for i in items if i.search_id in searches]


def for_schedule(session: Session, schedule_id: int) -> list[Found]:
    """일정(과 그 일정을 만든 초안)에 링크된 근거, 근거 id 차례. links 는 그 범위의 링크만."""
    links = _schedule_links(session, schedule_id)
    return _found(session, (x.evidence_id for x in links), links)


def for_chat(session: Session, chat_session_id: int) -> list[Found]:
    """그 대화의 검색이 찾은 근거, 근거 id 차례. links 는 그 근거의 모든 링크."""
    searches = select(EvidenceSearch.id).where(EvidenceSearch.chat_session_id == chat_session_id)
    ids = list(session.scalars(select(EvidenceItem.id).where(EvidenceItem.search_id.in_(searches))))
    links = list(session.scalars(select(EvidenceLink).where(EvidenceLink.evidence_id.in_(ids)).order_by(EvidenceLink.id)))
    return _found(session, ids, links)


def for_conditions(session: Session, schedule_id: int) -> dict[str, list[EvidenceItem]]:
    """조건 id → 그 조건을 받친 근거(근거 id 차례, 겹치지 않게). 일정과 그 일정을 만든 초안의 링크."""
    links = [x for x in _schedule_links(session, schedule_id) if x.condition_id is not None]
    if not links:
        return {}
    items = {i.id: i for i in session.scalars(select(EvidenceItem).where(EvidenceItem.id.in_({x.evidence_id for x in links})))}
    out: dict[str, list[EvidenceItem]] = {}
    for condition_id in dict.fromkeys(x.condition_id for x in links):
        ids = sorted({x.evidence_id for x in links if x.condition_id == condition_id and x.evidence_id in items})
        out[condition_id] = [items[i] for i in ids]
    return out
