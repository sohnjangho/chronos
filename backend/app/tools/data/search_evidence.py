"""evidence.search — 분야 기준값(예: 층당 골조 기간)의 근거를 Liner 검색(web·scholar)으로 찾아 보관한다.

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
from app.llm import search
from app.store.evidence import last_user_message_at, record_search, searches_since
from app.store.tables import EvidenceItem, EvidenceSearch
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool

logger = logging.getLogger(__name__)

LIMIT = 3
LIMIT_MESSAGE = "이번 요청에서 근거 검색을 3번 했습니다. 찾은 근거나 분야 기본값을 쓰세요."
FALLBACK = "근거 없이 분야 기본값을 쓰고 '근거 검색 실패'라고 적으세요."
NOT_READY_CODE = "not_ready"
DESCRIPTION_MAX = 300  # 에이전트에게 보이는 요약 길이(표에는 받은 글 전체)


class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=300, description="찾을 말(예: 철근콘크리트 층당 골조 공기)")
    mode: search.SearchMode = Field(default="web", description="web = 웹, scholar = 학술 문헌")
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


def _used_before(ctx: ToolContext) -> int:
    if ctx.chat_session_id is None:
        return 0
    since = last_user_message_at(ctx.session, ctx.chat_session_id)
    return searches_since(ctx.session, ctx.chat_session_id, since)


def _record_failure(ctx: ToolContext, args: SearchIn, code: str, latency_ms: int) -> None:
    """실패 줄을 따로 연 짧은 세션에 저장한다. 저장이 안 돼도 도구의 결과(실패 안내)는 그대로다."""
    try:
        with Session(ctx.session.get_bind(EvidenceSearch)) as recorder:
            record_search(recorder, chat_session_id=ctx.chat_session_id, query=args.query, mode=args.mode, ok=False,
                          error_code=code, latency_ms=latency_ms, hits=[])
            recorder.commit()
    # 예외 글에 SQL 과 값이 들어 있을 수 있어 종류만 남긴다.
    except Exception as exc:  # noqa: BLE001
        logger.warning("근거 검색 실패 기록 저장 실패 (%s)", type(exc).__name__)


def _hit(item: EvidenceItem) -> HitOut:
    return HitOut(evidence_id=item.id, title=item.title, url=item.url, hostname=item.hostname,
                  description=item.description[:DESCRIPTION_MAX], date=item.published,
                  authors=item.extra_json.get("authors", []), journal=item.extra_json.get("journal"))


def _card(search_id: int, args: SearchIn, results: list[HitOut]) -> AgentEvent:
    keep = ("evidence_id", "title", "url", "hostname", "date")
    rows = [{k: getattr(r, k) for k in keep} for r in results]
    return AgentEvent("card", {"kind": "evidence", "search_id": search_id, "query": args.query, "mode": args.mode,
                               "results": rows})


@tool(
    "evidence.search",
    "분야 기준값(예: 철근콘크리트 층당 골조 기간)의 근거를 웹(web)이나 학술 문헌(scholar)에서 찾아 보관한다. "
    "한 요청에 3번까지(실패 포함). 결과마다 evidence_id 가 있다: 그 값으로 정한 가정의 evidence_ids 에 넣고, "
    "생성 뒤 evidence__attach 로 초안·조건에 붙인다. 실패하면 분야 기본값을 쓰고 '근거 검색 실패'라고 적는다.",
    mutates=True,
)
async def search_evidence(args: SearchIn, ctx: ToolContext) -> SearchOut:
    used = _used_before(ctx)
    if used >= LIMIT:
        raise ToolError(LIMIT_MESSAGE)
    start = time.perf_counter()
    try:
        result = await search.liner_search(ctx.session, args.query, args.mode, max_results=args.max_results)
    except (search.SearchNotReady, search.SearchFailed) as e:
        code = e.code if isinstance(e, search.SearchFailed) else NOT_READY_CODE
        _record_failure(ctx, args, code, int((time.perf_counter() - start) * 1000))
        raise ToolError(f"{e.message} {FALLBACK}") from None
    search_id, items = record_search(ctx.session, chat_session_id=ctx.chat_session_id, query=args.query,
                                     mode=args.mode, ok=True, error_code=None, latency_ms=result.latency_ms,
                                     hits=result.hits)
    results = [_hit(i) for i in items]
    ctx.emit(_card(search_id, args, results))
    return SearchOut(search_id=search_id, used=used + 1, limit=LIMIT, results=results)
