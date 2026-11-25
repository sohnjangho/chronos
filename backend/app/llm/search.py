"""근거 검색: Liner Search API (`POST {base_url}/tools/search/{web|scholar}`). 분야 검색은 mcp_client.

- 기본 LLM 연결(provider `liner`)의 키를 서버에서 풀어 `x-api-key` 머리글로만 보낸다. 키·머리글은
  기록(log)·예외·결과 어디에도 담지 않는다. 실패는 종류만 남긴다.
- web 은 `include_knowledge: false` 로 Premium Data(knowledge 표, 1,000건당 $2)를 끈다(1,000건당 $1).
  관리 포인트 겨냥 검색만 liner_knowledge 로 켠다(app.points.risk).
- 다시 시도하지 않는다. 실패는 SearchFailed(code, 한국어 message), 부를 수 없으면 SearchNotReady.
- 결과는 http(s) 주소만 남긴다(화면이 링크로 그린다). 길이는 근거 표 칸(evidence_items)에 맞춰 자른다.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal

import httpx
from sqlalchemy.orm import Session

from app.llm import daily_cap
from app.llm.assignments import default_connection
from app.llm.connections import secret_is_sendable
from app.security.crypto import SecretUnreadable, decrypt

logger = logging.getLogger(__name__)

SearchMode = Literal["web", "scholar", "legal", "business"]
# 분야 검색(legal·business)은 Liner MCP 로 찾는다(app.llm.mcp_client.field_search). liner_search 는 web·scholar 만.
FIELD_MODES: tuple[SearchMode, ...] = ("legal", "business")

# 시험이 가짜 transport 를 바꿔 끼운다. None 이 아니면 liner_search 의 transport 인자 대신 쓴다.
TRANSPORT: httpx.AsyncBaseTransport | None = None

NO_CONNECTION = "근거 검색에는 Liner 연결이 필요합니다. 설정에서 연결해 주세요."
NOT_LINER = "근거 검색은 Liner 연결에서만 됩니다."
UNREADABLE_KEY = "저장된 키를 읽을 수 없습니다. 키를 다시 넣어 주세요."
FAILED_MESSAGES = {
    "bad_request": "검색 요청 형식이 맞지 않습니다.",
    "bad_key": "API 키가 맞지 않습니다.",
    "no_credit": "Liner 크레딧이 부족합니다.",
    "rate_limited": "호출 한도를 넘었습니다. 잠시 뒤 다시 해 주세요.",
    "server_error": "검색 서버에 문제가 생겼습니다.",
    "timeout": "응답이 너무 늦습니다.",
    "bad_url": "주소에 연결할 수 없습니다.",
    "unknown": "검색 결과를 읽지 못했습니다.",
}
_STATUS_CODES = {400: "bad_request", 401: "bad_key", 402: "no_credit", 403: "bad_key", 404: "bad_url", 429: "rate_limited"}
_SERVER_ERROR_FROM = 500
# 통신 실패·시간 초과·읽을 수 없는 응답(JSON 아님·results 없음)
_FAILURES = (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError, TypeError)
# 근거 표 칸 길이(evidence_items): 제목 300 · 주소 1000 · 호스트 200 · 날짜 20
_TITLE, _URL, _HOST, _DATE = 300, 1000, 200, 20


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    hostname: str
    description: str
    date: str | None
    authors: tuple[str, ...] = ()  # scholar 만
    journal: str | None = None  # scholar 만
    citation_count: int | None = None  # scholar 만


@dataclass(frozen=True)
class SearchResult:
    hits: list[SearchHit]
    latency_ms: int


class SearchNotReady(Exception):
    """부를 수 없다(연결 없음·Liner 연결 아님·키를 읽을 수 없음). 보내지 않았다."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SearchFailed(Exception):
    """불렀지만 실패했다. code 는 FAILED_MESSAGES 의 열쇠, message 는 화면·에이전트에 보일 설명."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or FAILED_MESSAGES[code])
        self.code = code
        self.message = message or FAILED_MESSAGES[code]


class _Unreadable(ValueError):
    """200 이지만 results 목록이 없다(→ unknown)."""


def _target(session: Session) -> tuple[str, str]:
    """(주소, 키). 부른 쪽 세션의 쌓인 변경을 flush 하지 않는다(쓰기 잠금을 쥔 채 기다리지 않게)."""
    with session.no_autoflush:
        conn = default_connection(session)
    if conn is None:
        raise SearchNotReady(NO_CONNECTION)
    if conn.provider != "liner":
        raise SearchNotReady(NOT_LINER)
    try:
        key = decrypt(conn.secret_ciphertext)
    except SecretUnreadable:
        raise SearchNotReady(UNREADABLE_KEY) from None
    if not secret_is_sendable(key):  # 머리글에 실을 수 없는 키는 보내지 않는다
        raise SearchNotReady(UNREADABLE_KEY)
    return conn.base_url.rstrip("/"), key


def _body(query: str, mode: SearchMode, max_results: int) -> dict:
    body: dict = {"query": query, "max_results": max_results}
    if mode == "web":
        body["include_knowledge"] = False  # snake_case 만 인정된다
    return body


def _code(exc: BaseException) -> str:
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return "server_error" if status >= _SERVER_ERROR_FROM else _STATUS_CODES.get(status, "unknown")
    if isinstance(exc, httpx.InvalidURL | httpx.UnsupportedProtocol | httpx.ConnectError):
        return "bad_url"
    return "unknown"


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _web_url(value: object) -> tuple[str, str] | None:
    """(주소, 호스트). 링크로 그릴 수 있는 주소(http·https, 호스트 있음, 1000자 이하)만, 아니면 None."""
    text = _text(value)
    if not text or len(text) > _URL:
        return None
    try:
        url = httpx.URL(text)
    except httpx.InvalidURL:
        return None
    return (text, url.host) if url.scheme in ("http", "https") and url.host else None


def _hit(item: object) -> SearchHit | None:
    """results[] 한 줄. 객체가 아니거나 링크로 쓸 주소가 없으면 None(버린다). 주소는 받은 글 그대로."""
    if not isinstance(item, dict) or (found := _web_url(item.get("url"))) is None:
        return None
    link, host = found
    authors = item.get("authors")
    count = item.get("citationCount")
    return SearchHit(
        title=(_text(item.get("title")) or link)[:_TITLE],
        url=link,
        hostname=(_text(item.get("hostname")) or host)[:_HOST],
        description=_text(item.get("description")),
        date=_text(item.get("date"))[:_DATE] or None,
        authors=tuple(a for a in authors if isinstance(a, str)) if isinstance(authors, list) else (),
        journal=_text(item.get("journal")) or None,
        citation_count=count if isinstance(count, int) and not isinstance(count, bool) else None,
    )


def _hits(data: object, max_results: int) -> list[SearchHit]:
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise _Unreadable
    hits = [h for h in map(_hit, data["results"]) if h is not None]
    return hits[:max_results]


def check_cap(session: Session) -> None:
    """오늘 LLM 비용 상한(app.llm.daily_cap)에 닿았으면 SearchFailed(daily_cap) — 보내지 않는다."""
    try:
        daily_cap.check(session)
    except daily_cap.DailyCapReached as capped:
        raise SearchFailed(capped.code, capped.message) from None


async def _send(session: Session, mode: SearchMode, body: dict, timeout_s: float,
                transport: httpx.AsyncBaseTransport | None, read):
    """한 번 보내고 read(받은 JSON) 를 돌려준다. 부를 수 없으면 SearchNotReady, 보낸 뒤 실패하면 SearchFailed."""
    base_url, key = _target(session)
    check_cap(session)
    chosen = TRANSPORT if TRANSPORT is not None else transport
    code: str | None = None
    out = None
    try:
        async with asyncio.timeout(timeout_s):
            # trust_env=False: 환경 변수의 프록시로 키가 나가지 않게 한다. httpx 는 스스로 다시 시도하지 않는다.
            async with httpx.AsyncClient(transport=chosen, timeout=timeout_s, trust_env=False) as http:
                response = await http.post(
                    f"{base_url}/tools/search/{mode}",
                    headers={"x-api-key": key, "Content-Type": "application/json"},
                    json=body,
                )
        response.raise_for_status()
        out = read(response.json())
    except _FAILURES as exc:
        code = _code(exc)
        # 예외 내용은 남기지 않는다(요청 머리글을 들고 있을 수 있다). 종류만 남긴다.
        logger.warning("근거 검색 실패: mode=%s code=%s (%s)", mode, code, type(exc).__name__)
    if code is not None:
        # except 밖에서 던져 원래 예외(요청 객체를 들고 있다)가 따라붙지 않게 한다.
        raise SearchFailed(code)
    return out


async def liner_search(
    session: Session,
    query: str,
    mode: SearchMode = "web",
    *,
    max_results: int = 5,
    timeout_s: float = 20,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SearchResult:
    """web·scholar 로 한 번 찾는다. 부를 수 없으면 SearchNotReady(보내지 않음), 보낸 뒤 실패하면 SearchFailed.

    timeout_s 는 호출 전체에 건다. 받은 세션은 읽기만 한다(commit·flush 하지 않는다).
    """
    start = time.perf_counter()
    hits = await _send(session, mode, _body(query, mode, max_results), timeout_s, transport,
                       lambda data: _hits(data, max_results))
    return SearchResult(hits, int((time.perf_counter() - start) * 1000))


def _whole(data: object) -> dict:
    if not isinstance(data, dict):
        raise _Unreadable
    return data


async def liner_knowledge(
    session: Session,
    query: str,
    *,
    max_results: int = 3,
    timeout_s: float = 20,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """관리 포인트 겨냥 검색(계획 5): web 을 `include_knowledge: true`(Premium Data, 1,000건당 $2)로 한 번 부르고 받은
    본문(dict)을 그대로 돌려준다 — `app.llm.knowledge.read` 로 표를 읽는다. country_code·lang 은 보내지 않는다.

    일반 근거 검색(liner_search)은 그대로 끈다. 실패·부를 수 없음은 liner_search 와 같다. 세션은 읽기만 한다.
    """
    body = {"query": query, "max_results": max_results, "include_knowledge": True}
    return await _send(session, "web", body, timeout_s, transport, _whole)
