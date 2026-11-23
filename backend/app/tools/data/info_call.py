"""info.call — 범용(generic) 정보 API 연결 하나를 GET 으로 한 번 부르고, 응답을 근거로 남긴다.

- 판단(어느 연결·경로·파라미터)은 에이전트, 호출은 코드(app.info.generic): 연결 주소 + path 에 키를 붙여 부른다.
- 응답은 JSON 그대로, XML 은 JSON 꼴로, 에이전트에게는 JSON 글로 옮겨 3,500자까지(잘리면 truncated 와 「범위를 좁혀」 안내).
  결과 칸은 evidence_id·truncated 를 body 앞에 둔다(도구 결과 4,000자 한도에 잘려도 남게).
- 결과는 근거(evidence_searches mode "info" + evidence_items 한 줄: 제목 = 연결 이름 + path, 출처 = 연결 이름,
  주소 = 키를 뺀 부른 주소, 본문 앞부분)로 넣고 evidence_id 를 돌려준다. 카드는 근거 카드.
- 한 요청(그 대화의 마지막 사용자 메시지 뒤)에 LIMIT 번까지(실패 포함). 날씨 조회·근거 검색과 따로 센다.
  인자가 틀린 것(없는 연결·kma 연결·안 되는 경로·주소를 만들 수 없는 params)은 부르기 전에 거절하고 세지 않는다.
- 실패 안내에는 HTTP 상태와 응답 앞 300자(키 지움)를 붙여 에이전트가 호출을 고칠 수 있게 한다.
- 부르기 전에는 DB 에 쓰지 않는다(루프가 도구 전에 commit 했다). 성공 줄은 받은 세션에 flush 만(루프가 commit),
  실패 줄은 따로 연 짧은 세션에 바로 저장한다(루프가 rollback 해도 한도에 들게). 키는 출력·카드·기록에 없다.
"""

import logging
import time
from typing import Annotated

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agent.events import AgentEvent
from app.info import generic
from app.info.generic import GenericConn, GenericFailed
from app.llm.search import SearchHit
from app.security.crypto import SecretUnreadable, decrypt
from app.store.evidence import (
    INFO_MODE,
    last_user_message_at,
    record_search,
    searches_since,
)
from app.store.tables import EvidenceSearch, InfoConnection
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool

logger = logging.getLogger(__name__)

LIMIT = 4
LIMIT_MESSAGE = "이번 요청에서 정보 API 조회를 4번 했습니다. 받은 값이나 분야 기본값을 쓰세요."
FALLBACK = ("쓰는 법(usage)대로 path·params 를 고쳐 다시 부르거나, 분야 기본값을 쓰고 '근거 없음, 분야 기본값'이라고 "
            "적으세요. 값을 지어내지 마세요.")
NOT_FOUND = "없는 정보 API 연결입니다: {id} — info__list 로 연결 id 를 확인하세요."
KMA_ONLY = "기상청 전용 연결입니다. 날씨는 info__weather 로 보세요."
UNREADABLE_KEY = "저장된 서비스키를 읽을 수 없습니다. 관리자에게 설정의 정보 API 연결에서 키를 다시 넣어 달라고 알리세요."
TITLE_MAX, URL_MAX = 300, 1000

ParamName = Annotated[str, Field(min_length=1, max_length=100)]
ParamValue = Annotated[str, Field(max_length=500)]


class CallIn(BaseModel):
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)

    connection_id: int = Field(description="info__list 의 id(kind generic 인 연결)")
    path: str = Field(min_length=1, max_length=500,
                      description="연결 주소 뒤에 붙일 / 로 시작하는 상대 경로(예: /getRestDeInfo). 쓰는 법(usage)대로")
    params: dict[ParamName, ParamValue] = Field(default_factory=dict, max_length=30,
                                          description="질의 값(이름 → 값). 키는 넣지 않는다 — 코드가 붙인다")


class CallOut(BaseModel):
    """칸 차례가 뜻이 있다: 도구 결과가 길어 잘려도 evidence_id·truncated 는 body 앞이라 남는다."""

    ok: bool
    http_status: int
    content_type: str  # 100자까지, 키를 지웠다
    evidence_id: int
    truncated: bool
    body: str  # JSON 글로 옮겨 3,500자까지, 키를 지웠다


def _connection(ctx: ToolContext, connection_id: int) -> InfoConnection:
    with ctx.session.no_autoflush:
        row = ctx.session.get(InfoConnection, connection_id)
    if row is None or row.preset not in ("kma", "generic"):
        raise ToolError(NOT_FOUND.format(id=connection_id))
    if row.preset == "kma":
        raise ToolError(KMA_ONLY)
    return row


def _used(ctx: ToolContext) -> int:
    if ctx.chat_session_id is None:
        return 0
    since = last_user_message_at(ctx.session, ctx.chat_session_id)
    return searches_since(ctx.session, ctx.chat_session_id, since, info=True)


def _record_failure(ctx: ToolContext, query: str, code: str, latency_ms: int) -> None:
    try:
        with Session(ctx.session.get_bind(EvidenceSearch)) as recorder:
            record_search(recorder, chat_session_id=ctx.chat_session_id, query=query, mode=INFO_MODE, ok=False,
                          error_code=code, latency_ms=latency_ms, hits=[])
            recorder.commit()
    except Exception as exc:  # noqa: BLE001 — 예외 글에 SQL 과 값이 있을 수 있어 종류만 남긴다
        logger.warning("정보 API 조회 실패 기록 저장 실패 (%s)", type(exc).__name__)


def _card(search_id: int, query: str, evidence_id: int, hit: SearchHit) -> AgentEvent:
    return AgentEvent("card", {"kind": "evidence", "search_id": search_id, "query": query, "mode": INFO_MODE,
                               "results": [{"evidence_id": evidence_id, "title": hit.title, "url": hit.url,
                                            "hostname": hit.hostname, "date": None}]})


@tool(
    "info.call",
    "범용(generic) 정보 API 연결 하나를 GET 으로 한 번 부른다. connection_id 는 info__list 의 id, path 는 연결 주소 뒤에 "
    "붙일 / 로 시작하는 상대 경로, params 는 질의 값 — 둘 다 그 연결의 usage(쓰는 법)대로 짠다. 키는 코드가 붙이므로 "
    "넣지 않는다. body 는 응답 본문(JSON, XML 은 JSON 꼴) 앞 3,500자이고 잘리면 truncated — 범위를 좁혀 다시 부른다. "
    "body 에 있는 값만 인용하고, 결과의 evidence_id 를 가정의 evidence_ids 에 넣는다. 한 요청에 4번까지(실패 포함, 날씨 "
    "조회·근거 검색과 따로 셈). kma(기상청) 연결은 info__weather 로 본다.",
    mutates=True,
)
async def info_call(args: CallIn, ctx: ToolContext) -> CallOut:
    row = _connection(ctx, args.connection_id)
    if (problem := generic.request_problem(args.path, args.params, row.key_name)) is not None:
        raise ToolError(problem)
    used = _used(ctx)
    if used >= LIMIT:
        raise ToolError(LIMIT_MESSAGE)
    name, base_url, key_in, key_name = row.name, row.base_url, row.key_in, row.key_name
    start = time.perf_counter()
    try:
        key = decrypt(row.secret_ciphertext)
    except SecretUnreadable:
        _record_failure(ctx, f"{name} {args.path}"[:TITLE_MAX], "not_ready", 0)
        raise ToolError(f"{UNREADABLE_KEY} {FALLBACK}") from None
    title = generic.scrub(f"{name} {args.path}", key, key_name=key_name)[:TITLE_MAX]
    conn = GenericConn(name=name, base_url=base_url, key=key, key_in=key_in, key_name=key_name)
    try:
        got = await generic.fetch(conn, args.path, args.params)
    except GenericFailed as e:
        if e.code == "bad_path":  # 부르기 전에 막힌 인자 오류 — 세지 않는다
            raise ToolError(e.message) from None
        _record_failure(ctx, title, e.code, int((time.perf_counter() - start) * 1000))
        seen = f" (HTTP {e.http_status}) 응답 앞부분: {e.sample}" if e.http_status is not None else ""
        raise ToolError(f"{e.message}{seen} {FALLBACK}") from None
    body, truncated = generic.body_for_model(got.text, got.cut)
    hit = SearchHit(title=title, url=got.url[:URL_MAX], hostname=httpx.URL(base_url).host, description=body,
                    date=None)
    query = got.url.removeprefix(base_url.rstrip("/"))  # 경로와 질의(키 없음)
    search_id, items = record_search(ctx.session, chat_session_id=ctx.chat_session_id, query=f"{name} {query}",
                                     mode=INFO_MODE, ok=True, error_code=None,
                                     latency_ms=int((time.perf_counter() - start) * 1000), hits=[hit])
    ctx.emit(_card(search_id, f"{name} {query}", items[0].id, hit))
    return CallOut(ok=True, http_status=got.http_status, content_type=got.content_type, evidence_id=items[0].id,
                   truncated=truncated, body=body)
