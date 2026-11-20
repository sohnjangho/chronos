"""evidence.search — 분야 기준값(예: 층당 골조 기간)의 근거를 Liner 검색으로 찾아 보관한다.

- mode web·scholar 는 Search API, legal·business 는 Liner MCP 의 분야 도구(search_legal·search_business).
  분야 검색이 실패하면 같은 질의로 web 을 한 번 해 보고 카드에 「분야 검색 실패 → 웹 검색」을 적는다(한도에 센다).

- 한 요청(그 대화의 마지막 사용자 메시지 뒤)에 LIMIT 번까지(실패 포함). 대화 밖에서 부르면 세지 않는다.
- 결과는 evidence_items 에 넣고 evidence_id 로 돌려준다. 성공 줄은 받은 세션에 flush 만 한다(루프가 commit).
- 실패 줄은 따로 연 짧은 세션에 바로 저장한다. 루프가 실패한 도구의 쓰기를 되돌려도(rollback) 남아 한도에 들게.
- 키는 app.llm.search 가 서버에서만 다룬다. 이 도구의 출력·카드·기록에는 들어가지 않는다.
"""

import logging
import time

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agent.events import AgentEvent
from app.llm import mcp_client, search
from app.store.evidence import last_user_message_at, record_search, searches_since
from app.store.tables import EvidenceItem, EvidenceSearch
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool

logger = logging.getLogger(__name__)

LIMIT = 3
LIMIT_MESSAGE = "이번 요청에서 근거 검색을 3번 했습니다. 찾은 근거나 분야 기본값을 쓰세요."
FALLBACK = "근거 없이 분야 기본값을 쓰고 '근거 검색 실패'라고 적으세요."
NOT_READY_CODE = "not_ready"
FIELD_FALLBACK = "분야 검색 실패 → 웹 검색"
DESCRIPTION_MAX = 300  # 에이전트에게 보이는 요약 길이(표에는 받은 글 전체)


class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=300, description="찾을 말(예: 철근콘크리트 층당 골조 공기)")
    mode: search.SearchMode = Field(
        default="web",
        description="legal = 법령·인허가·법정 기간·작업 금지·안전 규정, business = 공급업체·자재·부품 리드타임, "
                    "scholar = 학술 문헌, web = 그 밖",
    )
    max_results: int = Field(default=5, ge=1, le=5, description="결과 수")


class HitOut(BaseModel):
    evidence_id: int
    title: str
    url: str
    hostname: str
    description: str  # 300자까지
    date: str | None
    authors: list[str]
    journal: str | None


class SearchOut(BaseModel):
    search_id: int
    used: int  # 이번 요청에서 이 검색까지 한 수
    limit: int
    results: list[HitOut]
    note: str | None = None  # 분야 검색이 실패해 웹으로 찾았으면 FIELD_FALLBACK


def _used_before(ctx: ToolContext) -> int:
    if ctx.chat_session_id is None:
        return 0
    since = last_user_message_at(ctx.session, ctx.chat_session_id)
    return searches_since(ctx.session, ctx.chat_session_id, since)


def _record_failure(ctx: ToolContext, args: SearchIn, mode: str, code: str, latency_ms: int) -> None:
    """실패 줄을 따로 연 짧은 세션에 저장한다. 저장이 안 돼도 도구의 결과(실패 안내)는 그대로다."""
    try:
        with Session(ctx.session.get_bind(EvidenceSearch)) as recorder:
            record_search(recorder, chat_session_id=ctx.chat_session_id, query=args.query, mode=mode, ok=False,
                          error_code=code, latency_ms=latency_ms, hits=[])
            recorder.commit()
    # 예외 글에 SQL 과 값이 들어 있을 수 있어 종류만 남긴다.
    except Exception as exc:  # noqa: BLE001
        logger.warning("근거 검색 실패 기록 저장 실패 (%s)", type(exc).__name__)


def _hit(item: EvidenceItem) -> HitOut:
    return HitOut(evidence_id=item.id, title=item.title, url=item.url, hostname=item.hostname,
                  description=item.description[:DESCRIPTION_MAX], date=item.published,
                  authors=item.extra_json.get("authors", []), journal=item.extra_json.get("journal"))


def _card(search_id: int, args: SearchIn, mode: str, results: list[HitOut], note: str | None) -> AgentEvent:
    keep = ("evidence_id", "title", "url", "hostname", "date")
    rows = [{k: getattr(r, k) for k in keep} for r in results]
    data = {"kind": "evidence", "search_id": search_id, "query": args.query, "mode": mode, "results": rows}
    return AgentEvent("card", data | ({"note": note} if note else {}))


class _Failed(Exception):
    """한 번 찾기가 실패했다(실패 줄은 이미 남겼다). fallback = 웹으로 다시 해 볼 수 있는 실패인지."""

    def __init__(self, message: str, fallback: bool) -> None:
        super().__init__(message)
        self.message, self.fallback = message, fallback


async def _find(ctx: ToolContext, args: SearchIn, mode: search.SearchMode) -> search.SearchResult:
    """mode 대로 한 번 찾는다. 실패하면 실패 줄을 남기고 _Failed."""
    start = time.perf_counter()
    try:
        if mode in search.FIELD_MODES:
            return await mcp_client.field_search(ctx.session, args.query, mode, max_results=args.max_results)
        return await search.liner_search(ctx.session, args.query, mode, max_results=args.max_results)
    except (search.SearchNotReady, search.SearchFailed) as e:
        failed = isinstance(e, search.SearchFailed)
        _record_failure(ctx, args, mode, e.code if failed else NOT_READY_CODE, int((time.perf_counter() - start) * 1000))
        raise _Failed(e.message, fallback=failed) from None


@tool(
    "evidence.search",
    "분야 기준값(예: 철근콘크리트 층당 골조 기간)의 근거를 찾아 보관한다. mode: 인허가·법정 기간·작업 금지·안전 규정은 "
    "legal, 공급업체·자재·부품 리드타임은 business, 학술 기준은 scholar, 그 밖은 web. "
    "한 요청에 3번까지(실패 포함, 분야 검색 실패 뒤 웹으로 다시 한 것도 센다). 결과마다 evidence_id 가 있다: 그 값으로 정한 가정의 evidence_ids 에 넣고, "
    "생성 뒤 evidence__attach 로 초안·조건에 붙인다. 실패하면 분야 기본값을 쓰고 '근거 검색 실패'라고 적는다.",
    mutates=True,
)
async def search_evidence(args: SearchIn, ctx: ToolContext) -> SearchOut:
    used = _used_before(ctx)
    if used >= LIMIT:
        raise ToolError(LIMIT_MESSAGE)
    mode, note = args.mode, None
    try:
        result = await _find(ctx, args, mode)
    except _Failed as e:
        # 분야 검색이 보낸 뒤 실패했고 한도가 남았으면 같은 질의로 web 을 한 번(한도에 센다).
        if mode not in search.FIELD_MODES or not e.fallback or used + 1 >= LIMIT:
            raise ToolError(f"{e.message} {FALLBACK}") from None
        used, mode, note = used + 1, "web", FIELD_FALLBACK
        try:
            result = await _find(ctx, args, mode)
        except _Failed as web:
            raise ToolError(f"{FIELD_FALLBACK}도 실패: {web.message} {FALLBACK}") from None
    search_id, items = record_search(ctx.session, chat_session_id=ctx.chat_session_id, query=args.query,
                                     mode=mode, ok=True, error_code=None, latency_ms=result.latency_ms,
                                     hits=result.hits)
    results = [_hit(i) for i in items]
    ctx.emit(_card(search_id, args, mode, results, note))
    return SearchOut(search_id=search_id, used=used + 1, limit=LIMIT, results=results, note=note)
