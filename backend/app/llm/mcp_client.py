"""분야 검색: Liner MCP(`{base_url}/mcp`)의 search_legal·search_business. 새 의존성 없이 httpx 로 부른다.

- Streamable HTTP: JSON-RPC 2.0 POST, `Accept: application/json, text/event-stream`. 응답이 SSE 면 `data:` 줄을 읽는다.
- 한 번 찾을 때마다 세션을 연다: initialize → notifications/initialized → tools/call. initialize 응답에
  `Mcp-Session-Id` 머리글이 있으면 이후 요청에 붙인다(11-20 실측: Liner 는 주지 않았다).
- 결과는 content 의 text JSON(실측: `{requestId, results[], totalCount}`) 또는 structuredContent 의 `results`.
- 키는 Authorization 머리글로만 보낸다. 실패는 app.llm.search 의 SearchFailed(같은 code·한국어 안내)로 바꾸고,
  기록에는 종류만 남긴다. 다시 시도하지 않는다.
"""

import asyncio
import json
import logging
import time

import httpx
from sqlalchemy.orm import Session

from app.llm import search
from app.llm.search import SearchFailed, SearchResult

logger = logging.getLogger(__name__)

FIELD_TOOLS = {"legal": "search_legal", "business": "search_business"}
PROTOCOL = "2025-06-18"
_CLIENT = {"name": "chronos", "version": "1.0"}
# JSON-RPC 의 요청 형식 오류(-32700 해석 · -32600 요청 · -32601 메서드 · -32602 인자). 그 밖은 서버 문제로 본다.
_REQUEST_ERRORS = frozenset({-32700, -32600, -32601, -32602})
_FAILURES = (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError, TypeError)


class _RpcFailed(ValueError):
    """JSON-RPC 오류·도구 오류(isError)·읽을 수 없는 결과. code 는 search.FAILED_MESSAGES 의 열쇠."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def mcp_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/mcp"


def _message(response: httpx.Response, request_id: int) -> dict:
    """응답 본문의 JSON-RPC 메시지. SSE 면 이 요청 id 의 result·error 를 담은 `data:` 줄."""
    if "text/event-stream" in response.headers.get("content-type", ""):
        for line in response.text.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                found = json.loads(line[5:])
            except ValueError:
                continue
            if isinstance(found, dict) and found.get("id") == request_id and ("result" in found or "error" in found):
                return found
        raise _RpcFailed("unknown")
    found = response.json()
    if not isinstance(found, dict):
        raise _RpcFailed("unknown")
    return found


async def _rpc(http: httpx.AsyncClient, url: str, headers: dict, request_id: int, method: str,
               params: dict) -> tuple[dict, httpx.Response]:
    response = await http.post(url, headers=headers,
                               json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    response.raise_for_status()
    message = _message(response, request_id)
    if "error" in message:
        error = message["error"]
        code = error.get("code") if isinstance(error, dict) else None
        raise _RpcFailed("bad_request" if code in _REQUEST_ERRORS else "server_error")
    result = message.get("result")
    if not isinstance(result, dict):
        raise _RpcFailed("unknown")
    return result, response


def _payloads(result: dict):
    yield result.get("structuredContent")
    content = result.get("content")
    for item in content if isinstance(content, list) else []:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            try:
                yield json.loads(item["text"])
            except ValueError:
                continue


def _rows(result: dict) -> list[dict]:
    if result.get("isError") is True:
        raise _RpcFailed("server_error")
    for data in _payloads(result):
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return [row for row in data["results"] if isinstance(row, dict)]
    raise _RpcFailed("unknown")


async def _call(http: httpx.AsyncClient, url: str, secret: str, name: str, arguments: dict) -> list[dict]:
    headers = {"Authorization": f"Bearer {secret}", "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    init, response = await _rpc(http, url, headers, 1, "initialize",
                                {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": _CLIENT})
    if session_id := response.headers.get("mcp-session-id"):
        headers["Mcp-Session-Id"] = session_id
    version = init.get("protocolVersion")
    headers["MCP-Protocol-Version"] = version if isinstance(version, str) and version else PROTOCOL
    note = await http.post(url, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    note.raise_for_status()
    result, _ = await _rpc(http, url, headers, 2, "tools/call", {"name": name, "arguments": arguments})
    return _rows(result)


async def call_tool(base_url: str, secret: str, name: str, arguments: dict, *, timeout: float = 30,
                    transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    """MCP 도구 하나를 부르고 검색 결과 줄([{title, url, description, date, …}])을 받은 그대로 돌려준다.

    timeout 은 세션 열기부터 결과까지 전체에 건다. 실패는 SearchFailed(code) — 원래 예외는 따라붙지 않는다.
    """
    code: str | None = None
    rows: list[dict] = []
    try:
        async with asyncio.timeout(timeout):
            # trust_env=False: 환경 변수의 프록시로 키가 나가지 않게 한다.
            async with httpx.AsyncClient(transport=transport, timeout=timeout, trust_env=False) as http:
                rows = await _call(http, mcp_url(base_url), secret, name, arguments)
    except _FAILURES as exc:
        code = exc.code if isinstance(exc, _RpcFailed) else search._code(exc)
        # 예외 내용은 남기지 않는다(요청 머리글을 들고 있을 수 있다). 종류만 남긴다.
        logger.warning("분야 검색 실패: tool=%s code=%s (%s)", name, code, type(exc).__name__)
    if code is not None:
        raise SearchFailed(code)  # except 밖에서 던져 원래 예외가 따라붙지 않게 한다
    return rows


async def field_search(session: Session, query: str, mode: search.SearchMode, *, max_results: int = 5,
                       timeout_s: float = 30, transport: httpx.AsyncBaseTransport | None = None) -> SearchResult:
    """기본 Liner 연결로 분야 검색(legal·business)을 한 번 한다. 결과는 웹 검색과 같은 규칙으로 고른다.

    부를 수 없으면 SearchNotReady(보내지 않음), 보낸 뒤 실패하면 SearchFailed. 세션은 읽기만 한다.
    """
    base_url, key = search._target(session)
    chosen = search.TRANSPORT if search.TRANSPORT is not None else transport
    start = time.perf_counter()
    rows = await call_tool(base_url, key, FIELD_TOOLS[mode], {"query": query, "limit": max_results},
                           timeout=timeout_s, transport=chosen)
    hits = [h for h in map(search._hit, rows) if h is not None][:max_results]
    return SearchResult(hits, int((time.perf_counter() - start) * 1000))
