"""실행 추적 읽기(trace_events)와 LLM 사용량 묶기(llm_calls·evidence_searches). 쓰기는 app.agent.trace 가 한다.

- 턴 = turn_id(그 턴의 사용자 메시지 id)가 같은 사건들. 턴의 시간은 첫 사건의 시작부터 end 사건까지
  (end 가 없으면 지금까지).
- 도구 안 LLM 호출 = 턴의 시간 안에 생긴 그 대화의 llm_calls 가운데 purpose 가 normal 이 아닌 것
  (루프 자신의 호출은 llm 사건으로 따로 있다).
- 턴의 모델 호출 수·토큰·비용 = llm 사건 + 도구 안 호출. 비용은 NULL 아닌 것만 더하고, 하나도 없으면 None.
- 시각은 UTC 로 저장되어 있다(시간대 없이). 사용량의 날(day)과 기간은 서울 날짜로 센다.
- 관리 포인트 겨냥 검색·근거 문장(계획 5)은 Liner 를 부르지만 근거 검색 수(NOT_SEARCH_MODES 밖)에 들지 않는다 — point_calls 가
  따로 센다: Search + Premium Data(mode knowledge) · MCP search_business(mode knowledge, 질의 「business: …」) ·
  Search Agent(llm_calls purpose srch_agent). 셋 다 대화 없이(chat_session_id 없음) 남는다.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, defer

from app.llm.search_agent import PURPOSE as SEARCH_AGENT_PURPOSE
from app.store.evidence import KNOWLEDGE_MODE, NOT_SEARCH_MODES
from app.store.tables import (
    ChatMessage,
    ChatSession,
    EvidenceSearch,
    LlmCall,
    TraceEvent,
    User,
)
from app.store.timeutil import as_utc
from app.store.workflows import step_counts

LOOP_PURPOSE = "normal"  # 루프가 부르는 쓰임새(도구 안 호출에서 뺀다)
OUTSIDE_CHAT = "대화 밖"  # 대화 없이 부른 호출의 사용자 이름
SEOUL = ZoneInfo("Asia/Seoul")
UsageGroup = Literal["model", "user", "day", "purpose"]


@dataclass(frozen=True)
class TurnRow:
    turn_id: int
    chat_session_id: int
    user_name: str
    content: dict  # 그 턴의 사용자 메시지 content_json(없어졌으면 {})
    started_at: datetime  # UTC
    ended_at: datetime | None  # end 사건의 시각(UTC). 없으면 None
    end_status: str | None  # end 사건의 label(done|failed|stopped). 없으면 None
    latest: bool  # 그 대화의 마지막 턴인가(돌고 있는 턴은 이것뿐이다)
    run_id: int | None
    llm_calls: int
    tool_calls: int
    tokens: int
    cost: float | None
    ms: int | None  # 턴 전체 시간(end 사건의 ms)


def _add_cost(total: float | None, cost: float | None) -> float | None:
    return total if cost is None else (total or 0.0) + cost


def _naive(dt: datetime) -> datetime:
    """DB 와 견줄 UTC(시간대 없음)."""
    return as_utc(dt).replace(tzinfo=None)


def events(session: Session, turn_id: int) -> list[TraceEvent]:
    """턴의 사건, seq 순."""
    query = select(TraceEvent).where(TraceEvent.turn_id == turn_id).order_by(TraceEvent.seq)
    return list(session.scalars(query))


def inner_calls(session: Session, chat_session_id: int, start: datetime, end: datetime | None) -> list[LlmCall]:
    """턴의 시간(start ~ end, end 가 없으면 지금) 안에 생긴 그 대화의 도구 안 LLM 호출, 생긴 순."""
    query = select(LlmCall).where(
        LlmCall.chat_session_id == chat_session_id, LlmCall.purpose != LOOP_PURPOSE,
        LlmCall.created_at >= _naive(start), LlmCall.created_at <= _naive(end or datetime.now(UTC)),
    )
    return list(session.scalars(query.order_by(LlmCall.created_at, LlmCall.id)))


def _inner_by_turn(
    session: Session, windows: dict[int, tuple[int, datetime, datetime | None]]
) -> dict[int, list[LlmCall]]:
    """턴마다 도구 안 LLM 호출(inner_calls 와 같은 규칙)을 질의 한 번으로."""
    out: dict[int, list[LlmCall]] = {tid: [] for tid in windows}
    if not windows:
        return out
    now = datetime.now(UTC)
    bounds = {tid: (chat, start, end or now) for tid, (chat, start, end) in windows.items()}
    query = select(LlmCall).where(
        LlmCall.chat_session_id.in_({chat for chat, _, _ in bounds.values()}), LlmCall.purpose != LOOP_PURPOSE,
        LlmCall.created_at >= _naive(min(s for _, s, _ in bounds.values())),
        LlmCall.created_at <= _naive(max(e for _, _, e in bounds.values())),
    )
    for call in session.scalars(query.order_by(LlmCall.created_at, LlmCall.id)):
        at = as_utc(call.created_at)
        for tid, (chat, start, end) in bounds.items():
            if call.chat_session_id == chat and start <= at <= end:
                out[tid].append(call)
    return out


def turns(session: Session, limit: int) -> list[TurnRow]:
    """추적이 있는 턴, 새것부터 limit 개."""
    query = select(TraceEvent.turn_id).group_by(TraceEvent.turn_id).order_by(TraceEvent.turn_id.desc()).limit(limit)
    return _rows(session, list(session.scalars(query)))


def turn(session: Session, turn_id: int) -> TurnRow | None:
    """턴 하나. 추적이 없으면 None."""
    rows = _rows(session, [turn_id])
    return rows[0] if rows else None


def _rows(session: Session, turn_ids: list[int]) -> list[TurnRow]:
    by_turn: dict[int, list[TraceEvent]] = defaultdict(list)
    query = (
        select(TraceEvent).where(TraceEvent.turn_id.in_(turn_ids)).order_by(TraceEvent.seq)
        .options(defer(TraceEvent.input_text), defer(TraceEvent.output_text))  # 큰 글 칸은 목록에서 쓰지 않는다
    )
    for event in session.scalars(query):
        by_turn[event.turn_id].append(event)
    chat_ids = {evs[0].chat_session_id for evs in by_turn.values()}
    names = dict(session.execute(
        select(ChatSession.id, User.name).join(User, User.id == ChatSession.user_id).where(ChatSession.id.in_(chat_ids))
    ).all())
    contents = dict(session.execute(
        select(ChatMessage.id, ChatMessage.content_json).where(ChatMessage.id.in_(list(by_turn)))
    ).all())
    latest = dict(session.execute(
        select(TraceEvent.chat_session_id, func.max(TraceEvent.turn_id))
        .where(TraceEvent.chat_session_id.in_(chat_ids)).group_by(TraceEvent.chat_session_id)
    ).all())
    runs = {tid: next((e.run_id for e in evs if e.run_id is not None), None) for tid, evs in by_turn.items()}
    steps = step_counts(session, [r for r in runs.values() if r is not None])
    windows = {}  # turn_id → (대화, 시작, 끝)
    for tid, evs in by_turn.items():
        end = next((e for e in evs if e.kind == "end"), None)
        windows[tid] = (evs[0].chat_session_id, min(as_utc(e.started_at) for e in evs),
                        as_utc(end.started_at) if end else None)
    inner = _inner_by_turn(session, windows)
    rows = []
    for tid in sorted(by_turn, reverse=True):
        evs = by_turn[tid]
        chat_id, start, ended = windows[tid]
        end = next((e for e in evs if e.kind == "end"), None)
        tokens, cost, llm_count = 0, None, 0
        for item in [*(e for e in evs if e.kind == "llm"), *inner[tid]]:
            llm_count += 1
            tokens += item.input_tokens + item.output_tokens
            cost = _add_cost(cost, item.cost)
        rows.append(TurnRow(
            turn_id=tid, chat_session_id=chat_id, user_name=names.get(chat_id, ""), content=contents.get(tid) or {},
            started_at=start, ended_at=ended, end_status=end.label if end else None, latest=latest[chat_id] == tid,
            run_id=runs[tid], llm_calls=llm_count, tool_calls=steps.get(runs[tid], 0), tokens=tokens, cost=cost,
            ms=end.ms if end else None,
        ))
    return rows


# ── 사용량 ──────────────────────────────────────────────────────────


class UsageTotals(BaseModel):
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None  # NULL 아닌 비용의 합. 하나도 없으면 null
    failed: int = 0

    def add(self, call: LlmCall) -> None:
        self.calls += 1
        self.input_tokens += call.input_tokens
        self.output_tokens += call.output_tokens
        self.cost = _add_cost(self.cost, call.cost)
        self.failed += 0 if call.ok else 1


class UsageRow(UsageTotals):
    key: str  # 모델 이름 · 사용자 이름("대화 밖") · 서울 날짜(YYYY-MM-DD) · 쓰임새


class SearchCount(BaseModel):
    calls: int
    failed: int


BUSINESS_QUERY_PREFIX = "business: "  # app.points.risk 업체 갈래 질의(MCP search_business)의 머리
LEGAL_QUERY_PREFIX = "legal: "  # app.points.risk 규제 갈래 질의(MCP search_legal)의 머리 — 같은 MCP 로 센다


class PointCalls(BaseModel):
    """관리 포인트가 부른 Liner 호출 수(실패 포함)."""

    knowledge: SearchCount  # Search + Premium Data(자재·환율)
    mcp: SearchCount  # MCP search_business·search_legal(업체·규제 소식)
    search_agent: SearchCount  # Search Agent(근거 문장)


def is_business(query: str) -> bool:
    """MCP 갈래(업체·규제) 질의인가."""
    return query.startswith((BUSINESS_QUERY_PREFIX, LEGAL_QUERY_PREFIX))


def _count(session: Session, model, ok, *where) -> SearchCount:
    calls, failed = session.execute(
        select(func.count(), func.coalesce(func.sum(case((ok.is_(False), 1), else_=0)), 0)).select_from(model).where(*where)
    ).one()
    return SearchCount(calls=calls, failed=int(failed))


def point_calls(session: Session, since: datetime, until: datetime | None = None) -> PointCalls:
    """since ~ until(없으면 끝 없음) 안에 생긴 관리 포인트의 Liner 호출 수."""
    def window(column) -> list:
        return [column >= _naive(since), *([column <= _naive(until)] if until is not None else [])]

    mcp = or_(EvidenceSearch.query.startswith(BUSINESS_QUERY_PREFIX, autoescape=True),
              EvidenceSearch.query.startswith(LEGAL_QUERY_PREFIX, autoescape=True))
    knowledge = [EvidenceSearch.mode == KNOWLEDGE_MODE, *window(EvidenceSearch.created_at)]
    return PointCalls(
        knowledge=_count(session, EvidenceSearch, EvidenceSearch.ok, *knowledge, ~mcp),
        mcp=_count(session, EvidenceSearch, EvidenceSearch.ok, *knowledge, mcp),
        search_agent=_count(session, LlmCall, LlmCall.ok, LlmCall.purpose == SEARCH_AGENT_PURPOSE,
                            *window(LlmCall.created_at)),
    )


class UsageOut(BaseModel):
    rows: list[UsageRow]  # day 면 날짜 순, 그 밖은 호출 많은 순(같으면 key 순)
    totals: UsageTotals
    cost_known: bool  # 비용을 알린 호출이 하나라도 있는가
    searches: SearchCount  # 근거 검색(evidence_searches)


def _since(days: int) -> datetime:
    """오늘(서울)을 넣어 days 날 전 서울 자정 → DB 와 견줄 UTC."""
    first = datetime.now(SEOUL).date() - timedelta(days=days - 1)
    return _naive(datetime(first.year, first.month, first.day, tzinfo=SEOUL))


def _key(group: UsageGroup, call: LlmCall, user_name: str | None) -> str:
    if group == "model":
        return call.model
    if group == "purpose":
        return call.purpose
    if group == "user":
        return user_name or OUTSIDE_CHAT
    return as_utc(call.created_at).astimezone(SEOUL).date().isoformat()


def usage(session: Session, *, days: int, group: UsageGroup) -> UsageOut:
    """최근 days 날(서울 날짜, 오늘 포함)의 LLM 호출을 group 으로 묶은 합과 근거 검색 수."""
    since = _since(days)
    query = (
        select(LlmCall, User.name)
        .outerjoin(ChatSession, ChatSession.id == LlmCall.chat_session_id)
        .outerjoin(User, User.id == ChatSession.user_id)
        .where(LlmCall.created_at >= since)
    )
    buckets: dict[str, UsageRow] = {}
    totals = UsageTotals()
    for call, user_name in session.execute(query):
        key = _key(group, call, user_name)
        buckets.setdefault(key, UsageRow(key=key)).add(call)
        totals.add(call)
    order = (lambda r: r.key) if group == "day" else (lambda r: (-r.calls, r.key))
    searched = session.execute(
        select(func.count(), func.coalesce(func.sum(EvidenceSearch.ok == False), 0))
        .where(EvidenceSearch.created_at >= since, EvidenceSearch.mode.notin_(NOT_SEARCH_MODES))  # 날씨·정보 API 조회는 빼고 센다
    ).one()
    return UsageOut(rows=sorted(buckets.values(), key=order), totals=totals, cost_known=totals.cost is not None,
                    searches=SearchCount(calls=searched[0], failed=int(searched[1])))
