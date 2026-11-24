"""근거 문장: Liner Search Agent(`POST {base_url}/agents/search`, stream:false) 의 출처 문장(referenceChunks)과 링크만 읽는다.

- 답 본문(answer·text-delta)은 버린다 — 화면에는 출처 문장과 링크만 보인다(지시서 C).
- 실패는 HTTP 200 안의 `data-error` 로도 온다. `[DONE]` 만 있고 문장이 없으면 빈 성공이 아니라 실패(no_quotes).
- stream:false 응답 모양은 문서가 정확히 적지 않았다: JSON({answer, references, chunks}) 과 SSE(`data:` 줄) 둘 다 읽는다.
  어디에 있든 `referenceChunks` 목록의 문장을 모으고, 링크는 그 줄의 url·title 이나 `references`(번호·id)에서 찾는다.
- 키는 기본 LLM 연결(provider liner)의 것을 서버에서 풀어 `x-api-key` 머리글로만 보낸다. 기록·예외·llm_calls 에 담지 않는다.
- 다시 시도하지 않는다. 보낸 호출마다(실패 포함) llm_calls 에 한 줄(purpose search_agent). 비용은 Liner 가 알리지 않아
  문서 가격(1회 COST_PER_CALL)을 200 으로 받은 호출에만 적는다(data-error 는 과금 여부를 몰라 비운다).
- 30초 안팎 걸린다(상한 300초): 부르는 쪽은 뒤에서 부른다(app.points.quotes).
"""

import asyncio
import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

import httpx
from sqlalchemy.orm import Session

from app.llm import fake
from app.llm.assignments import default_connection
from app.llm.client import LlmClient, LlmReply, Usage, _Target
from app.llm.connections import secret_is_sendable
from app.llm.errors import LlmError
from app.llm.search import _web_url
from app.security.crypto import SecretUnreadable, decrypt

logger = logging.getLogger(__name__)

# 시험이 가짜 transport 를 바꿔 끼운다. None 이면 CHRONOS_FAKE_LLM=1 일 때 가짜 Liner(밖으로 나가지 않음), 아니면 실제 Liner.
TRANSPORT: httpx.AsyncBaseTransport | None = None
PURPOSE = "search_agent"
MODEL = "liner-search-agent"  # llm_calls 의 모델 칸(요청에 model 을 넣지 않는다 — 서버 기본)
COST_PER_CALL = 0.02  # 문서 가격 $20/1K
TIMEOUT_S = 300.0  # 문서 상한

MESSAGES = {
    "no_connection": "근거 문장에는 Liner 연결이 필요합니다.",
    "bad_request": "요청 형식이 맞지 않습니다.",
    "bad_key": "API 키가 맞지 않습니다.",
    "no_credit": "Liner 크레딧이 부족합니다.",
    "rate_limited": "호출 한도를 넘었습니다.",
    "server_error": "Search Agent 서버에 문제가 생겼습니다.",
    "timeout": "응답이 너무 늦습니다.",
    "bad_url": "주소에 연결할 수 없습니다.",
    "agent_error": "Search Agent 가 실패를 알렸습니다.",
    "no_quotes": "출처 문장이 오지 않았습니다.",
}
_STATUS_CODES = {400: "bad_request", 401: "bad_key", 402: "no_credit", 403: "bad_key", 404: "bad_url", 429: "rate_limited"}
_FAILURES = (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError, TypeError)
_TEXT_KEYS = ("text", "chunk", "content", "sentence")
_ID_KEYS = ("referenceId", "referenceIndex", "index", "id")
_TEXT, _TITLE = 2000, 300


@dataclass(frozen=True)
class AgentQuote:
    text: str
    url: str
    title: str


class SearchAgentFailed(Exception):
    """문장을 받지 못했다. code 는 MESSAGES 의 열쇠(키·받은 글은 담지 않는다)."""

    def __init__(self, code: str) -> None:
        super().__init__(MESSAGES[code])
        self.code = code
        self.message = MESSAGES[code]


class _Failed(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _target(session: Session) -> _Target | None:
    with session.no_autoflush:  # 부른 쪽 세션의 쌓인 변경을 flush 하지 않는다
        conn = default_connection(session)
    if conn is None or conn.provider != "liner":
        return None
    try:
        key = decrypt(conn.secret_ciphertext)
    except SecretUnreadable:
        return None
    return _Target(conn.base_url.rstrip("/"), MODEL, None, key) if secret_is_sendable(key) else None


def _code(exc: BaseException) -> str:
    if isinstance(exc, _Failed):
        return exc.code
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return "server_error" if status >= 500 else _STATUS_CODES.get(status, "bad_request")
    if isinstance(exc, httpx.InvalidURL | httpx.UnsupportedProtocol | httpx.ConnectError):
        return "bad_url"
    return "no_quotes"


def _events(response: httpx.Response) -> list[object]:
    """SSE 면 `data:` 줄마다 JSON 하나([DONE]·읽을 수 없는 줄은 건넌다), 아니면 JSON 본문 하나."""
    text = response.text
    if not response.headers.get("content-type", "").startswith("text/event-stream") and not text.lstrip().startswith("data:"):
        return [response.json()]
    found: list[object] = []
    for line in text.splitlines():
        payload = line[5:].strip() if line.startswith("data:") else ""
        if payload and payload != "[DONE]":
            try:
                found.append(json.loads(payload))
            except ValueError:
                continue
    return found


def _dicts(value: object) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _dicts(v)
    elif isinstance(value, list):
        for v in value:
            yield from _dicts(v)


def _str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _link(item: dict, refs: dict[object, dict]) -> tuple[str, str] | None:
    """(주소, 제목). 그 줄의 url, 안의 reference, 아니면 references 의 번호·id 로 찾는다. http(s) 만."""
    for source in (item, item.get("reference"), *(refs.get(item.get(k)) for k in _ID_KEYS)):
        if isinstance(source, dict) and (found := _web_url(source.get("url"))) is not None:
            return found[0], (_str(source.get("title")) or found[1])[:_TITLE]
    return None


def _quotes(events: list[object]) -> list[AgentQuote]:
    every = list(_dicts(events))
    if any(d.get("type") == "data-error" for d in every):
        raise _Failed("agent_error")
    refs: dict[object, dict] = {}
    for d in every:
        if isinstance(d.get("references"), list):
            for n, ref in enumerate((r for r in d["references"] if isinstance(r, dict)), start=1):
                refs.setdefault(n, ref)  # 본문 인용 [n] 은 1부터
                for k in _ID_KEYS:
                    if isinstance(ref.get(k), str | int) and not isinstance(ref.get(k), bool):
                        refs.setdefault(ref[k], ref)
    out: list[AgentQuote] = []
    for d in every:
        chunks = d.get("referenceChunks")
        for item in chunks if isinstance(chunks, list) else []:
            if not isinstance(item, dict):
                continue
            text = next((t for k in _TEXT_KEYS if (t := _str(item.get(k)))), "")[:_TEXT]
            link = _link(item, refs)
            if text and link and (q := AgentQuote(text, *link)) not in out:
                out.append(q)
    if not out:
        raise _Failed("no_quotes")
    return out


async def ask(session: Session, question: str, *, mode: Literal["general", "scholar"] = "general",
              timeout: float = TIMEOUT_S) -> list[AgentQuote]:
    """한 번 묻고 출처 문장을 돌려준다. 못 받으면 SearchAgentFailed(code). 세션은 읽기만 한다.

    부르는 쪽은 commit 하지 않은 쓰기를 쥔 채 부르지 않는다(llm_calls 기록이 잠금을 기다린다).
    """
    target = _target(session)
    if target is None:
        raise SearchAgentFailed("no_connection")
    transport = TRANSPORT if TRANSPORT is not None else (fake.transport() if fake.enabled() else None)
    quotes: list[AgentQuote] = []
    code: str | None = None
    billed = False
    start = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            # trust_env=False: 환경 변수의 프록시로 키가 나가지 않게 한다. httpx 는 스스로 다시 시도하지 않는다.
            async with httpx.AsyncClient(transport=transport, timeout=timeout, trust_env=False) as http:
                response = await http.post(
                    f"{target.base_url}/agents/search",
                    headers={"x-api-key": target.secret, "Content-Type": "application/json"},
                    json={"messages": [{"role": "user", "content": question}], "mode": mode, "stream": False},
                )
        response.raise_for_status()
        billed = True
        quotes = _quotes(_events(response))
    except _FAILURES as exc:
        code = _code(exc)
        if code == "agent_error":
            billed = False
        # 예외 내용·받은 글은 남기지 않는다(요청 머리글·키를 들고 있을 수 있다). 종류만 남긴다.
        logger.warning("Search Agent 실패: mode=%s code=%s (%s)", mode, code, type(exc).__name__)
    latency_ms = int((time.perf_counter() - start) * 1000)
    reply = LlmReply(text="", tool_calls=[], model=MODEL, usage=Usage(0, 0, COST_PER_CALL if billed else None))
    error = LlmError(code, MESSAGES[code]) if code is not None else None
    # 기록은 스레드에서(새 세션) — SQLite 잠금을 기다려도 이벤트 루프가 멈추지 않게
    await asyncio.to_thread(LlmClient(session)._record, PURPOSE, target, None, latency_ms, reply, error)
    if code is not None:
        raise SearchAgentFailed(code)  # except 밖에서 던져 요청(머리글)을 든 예외가 따라붙지 않게
    return quotes
