"""근거 문장: Liner Search Agent(`POST {base_url}/agents/search`, stream:false) 의 출처 문장(referenceChunks)과 링크만 읽는다.

- 답 본문(answer·text-delta)은 버린다 — 화면에는 출처 문장과 링크만 보인다(지시서 C).
- 실패는 HTTP 200 안의 `data-error` 로도 온다. `[DONE]` 만 있고 문장이 없으면 빈 성공이 아니라 실패(no_quotes).
- 실측(11-24) stream:false 응답: application/json {answer, references, chunks}. 문장은 type data-search-chunks 인 chunk 의
  data.referenceChunks[{num, id, content, description, date, sourceTitle, sourceUrl}], 답은 ((n)) 으로 num 을 인용한다.
  답이 인용한 문장을 인용 차례로 먼저, 나머지를 뒤에, MAX_QUOTES 개까지. http(s) 링크 없는 문장은 버린다. SSE(`data:` 줄)도 읽는다.
  referenceChunks 가 없는 꼴도 온다(리허설 11-24): data.sortedReferenceItems[{index, reason}] → references[index] 의
  title·url·description(출처 설명). description 이 비면 reason 을 「요약:」을 붙여 쓴다(출처 문장으로 보이지 않게).
- 키는 기본 LLM 연결(provider liner)의 것을 서버에서 풀어 `x-api-key` 머리글로만 보낸다. 기록·예외·llm_calls 에 담지 않는다.
- 다시 시도하지 않는다. 보낸 호출마다(실패 포함) llm_calls 에 한 줄(purpose srch_agent). 비용은 Liner 가 알리지 않아
  문서 가격(1회 COST_PER_CALL)을 200 으로 받은 호출에만 적는다(data-error 는 과금 여부를 몰라 비운다).
- 30초 안팎 걸린다(상한 300초): 부르는 쪽은 뒤에서 부른다(app.points.quotes — prepare 로 짧게 읽고 call 로 기다린다).
- CHRONOS_FAKE_LLM=1(시험이 TRANSPORT 를 끼우지 않았을 때)이면 보내지 않고 FAKE_QUOTE 하나를 준다(연결·비용·기록 없음).
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

import httpx
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.llm import daily_cap, fake
from app.llm.assignments import default_connection
from app.llm.client import _Target
from app.llm.connections import secret_is_sendable
from app.llm.search import _web_url
from app.security.crypto import SecretUnreadable, decrypt
from app.store.tables import LlmCall

logger = logging.getLogger(__name__)

# 시험이 가짜 transport 를 바꿔 끼운다. None 이면 CHRONOS_FAKE_LLM=1 일 때 가짜 Liner(밖으로 나가지 않음), 아니면 실제 Liner.
TRANSPORT: httpx.AsyncBaseTransport | None = None
PURPOSE = "srch_agent"  # llm_calls.purpose 는 10자까지
MODEL = "liner-search-agent"  # llm_calls 의 모델 칸(요청에 model 을 넣지 않는다 — 서버 기본)
COST_PER_CALL = 0.02  # 문서 가격 $20/1K
TIMEOUT_S = 300.0  # 문서 상한
MAX_QUOTES = 3  # 위험 줄 하나에 붙일 문장 수
MAX_CHARS = 240  # 문장 하나의 길이(낱말 경계에서 자른다)
SUMMARY_LABEL = "요약:"  # 출처 문장이 아니라 Liner 가 쓴 까닭(reason)일 때 앞에 붙인다

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
_CITE = re.compile(r"\(\((\d+)\)\)")  # 답 본문의 인용 ((n))
_TITLE = 300


@dataclass(frozen=True)
class AgentQuote:
    text: str
    url: str
    title: str


FAKE_QUOTE = AgentQuote("가짜 근거 문장입니다(CHRONOS_FAKE_LLM=1 시험·시연 전용).", "https://example.com/fake-search-agent",
                        "가짜 출처")


class SearchAgentFailed(Exception):
    """문장을 받지 못했다. code 는 MESSAGES 의 열쇠(키·받은 글은 담지 않는다)."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or MESSAGES[code])
        self.code = code
        self.message = message or MESSAGES[code]


class _Failed(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fake() -> bool:
    """가짜 Liner 를 쓸 때(시험이 TRANSPORT 를 끼우지 않았고 CHRONOS_FAKE_LLM=1): 보내지 않고 정해진 문장을 준다."""
    return TRANSPORT is None and fake.enabled()


def prepare(session: Session) -> _Target:
    """부를 곳(주소·키). 연결이 없거나 쓸 수 없으면 SearchAgentFailed(no_connection). 세션은 읽기만 한다.

    뒤 작업은 짧은 세션으로 이것만 하고 닫은 뒤 call 로 기다린다(기다리는 동안 DB 연결을 쥐지 않게).
    """
    if _fake():
        return _Target("fake", MODEL, None, "")
    with session.no_autoflush:  # 부른 쪽 세션의 쌓인 변경을 flush 하지 않는다
        conn = default_connection(session)
    key = None
    if conn is not None and conn.provider == "liner":
        try:
            key = decrypt(conn.secret_ciphertext)
        except SecretUnreadable:
            key = None
    if key is None or not secret_is_sendable(key):
        raise SearchAgentFailed("no_connection")
    return _Target(conn.base_url.rstrip("/"), MODEL, None, key)


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


def _short(text: str) -> str:
    """빈칸을 하나로 접고 MAX_CHARS 를 넘으면 낱말 경계에서 자른다(…)."""
    text = " ".join(text.split())
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS]
    space = cut.rfind(" ")
    return (cut[:space] if space > MAX_CHARS // 2 else cut).rstrip() + "…"


def _cited(every: list[dict]) -> list[int]:
    """답 본문이 인용한 번호 ((n)) 를 처음 나온 차례로. 본문은 이 번호를 읽는 데만 쓰고 버린다."""
    answer = "".join(d["answer"] for d in every if isinstance(d.get("answer"), str))
    answer += "".join(d["delta"] for d in every if d.get("type") == "text-delta" and isinstance(d.get("delta"), str))
    return list(dict.fromkeys(int(n) for n in _CITE.findall(answer)))


def _num(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _chunks_of(every: list[dict], kind: str) -> list[dict]:
    """type data-search-chunks 인 chunk 들의 data[kind] 목록(객체만)."""
    found: list[dict] = []
    for d in every:
        data = d.get("data") if d.get("type") == "data-search-chunks" else None
        items = data.get(kind) if isinstance(data, dict) else None
        found += [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
    return found


def _from_reference_chunks(every: list[dict]) -> list[tuple[int | None, AgentQuote]]:
    """referenceChunks[{num, content, sourceTitle, sourceUrl}] → (num, 출처 문장)."""
    out: list[tuple[int | None, AgentQuote]] = []
    for item in _chunks_of(every, "referenceChunks"):
        text, link = _short(_str(item.get("content"))), _web_url(item.get("sourceUrl"))
        if text and link:
            out.append((_num(item.get("num")), AgentQuote(text, link[0], (_str(item.get("sourceTitle")) or link[1])[:_TITLE])))
    return out


def _from_sorted_references(every: list[dict]) -> list[tuple[int | None, AgentQuote]]:
    """referenceChunks 가 없는 꼴(실측 11-24 리허설): sortedReferenceItems[{index, reason[{value}]}] → references[index](0부터).

    문장은 그 참고 자료의 description(출처 설명). 비었으면 Liner 가 쓴 까닭(reason)을 「요약:」을 붙여 쓴다 — 출처 문장이 아니다.
    번호는 index + 1(답의 ((n)) 과 맞춘다).
    """
    refs = next((d["references"] for d in every if isinstance(d.get("references"), list)), [])
    out: list[tuple[int | None, AgentQuote]] = []
    for item in _chunks_of(every, "sortedReferenceItems"):
        index = _num(item.get("index"))
        ref = refs[index] if index is not None and 0 <= index < len(refs) else None
        if not isinstance(ref, dict) or (link := _web_url(ref.get("url"))) is None:
            continue
        text = _short(_str(ref.get("description")))
        if not text:
            reason = item.get("reason")
            parts = [r["value"] for r in reason if isinstance(r, dict) and isinstance(r.get("value"), str)] \
                if isinstance(reason, list) else []
            summary = _short("".join(parts))
            text = f"{SUMMARY_LABEL} {summary}" if summary else ""
        if text:
            out.append((index + 1, AgentQuote(text, link[0], (_str(ref.get("title")) or link[1])[:_TITLE])))
    return out


def _quotes(events: list[object]) -> list[AgentQuote]:
    """출처 문장: referenceChunks, 없으면 sortedReferenceItems 의 참고 자료. 답이 ((n)) 으로 인용한 것 먼저(인용 차례), 나머지, MAX_QUOTES 개."""
    every = list(_dicts(events))
    if any(d.get("type") == "data-error" for d in every):
        raise _Failed("agent_error")
    pairs = _from_reference_chunks(every) or _from_sorted_references(every)
    found: dict[int, AgentQuote] = {}
    rest: list[AgentQuote] = []
    for num, quote in pairs:
        if quote in found.values() or quote in rest:
            continue
        if num is not None and num not in found:
            found[num] = quote
        else:
            rest.append(quote)
    cited = _cited(every)
    order = [found[n] for n in cited if n in found] + [q for n, q in found.items() if n not in cited] + rest
    if not order:
        raise _Failed("no_quotes")
    return order[:MAX_QUOTES]


def _record(bind: Engine, latency_ms: int, cost: float | None, code: str | None) -> None:
    """llm_calls 한 줄을 따로 연 짧은 세션으로. 실패해도 경고(종류만)만 남기고 결과는 바꾸지 않는다."""
    try:
        with Session(bind) as recorder:
            recorder.add(LlmCall(purpose=PURPOSE, model=MODEL, requested_model=MODEL, routing_strategy=None,
                                 cost=cost, latency_ms=latency_ms, ok=code is None,
                                 error_code=code[:20] if code else None))
            recorder.commit()
    except Exception as exc:  # noqa: BLE001 — 예외 글에 SQL·값이 있을 수 있어 종류만 남긴다
        logger.warning("Search Agent 호출 기록 저장 실패 (%s)", type(exc).__name__)


async def call(target: _Target, bind: Engine, question: str, *, mode: Literal["general", "scholar"] = "general",
               timeout: float = TIMEOUT_S) -> list[AgentQuote]:
    """prepare 가 준 곳에 한 번 묻는다. DB 세션을 받지 않는다(기록은 bind 에 따로 연 짧은 세션). 못 받으면 SearchAgentFailed."""
    if target.base_url == "fake" and _fake():
        return [FAKE_QUOTE]  # 보내지 않았다 — 비용·기록 없음
    try:
        with Session(bind) as reader:  # 오늘 LLM 비용 상한(app.llm.daily_cap) — 짧게 읽고 닫는다
            daily_cap.check(reader)
    except daily_cap.DailyCapReached as capped:
        raise SearchAgentFailed(capped.code, capped.message) from None
    quotes: list[AgentQuote] = []
    code: str | None = None
    billed = False
    start = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            # trust_env=False: 환경 변수의 프록시로 키가 나가지 않게 한다. httpx 는 스스로 다시 시도하지 않는다.
            async with httpx.AsyncClient(transport=TRANSPORT, timeout=timeout, trust_env=False) as http:
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
    # 기록은 스레드에서(새 세션) — SQLite 잠금을 기다려도 이벤트 루프가 멈추지 않게
    await asyncio.to_thread(_record, bind, latency_ms, COST_PER_CALL if billed else None, code)
    if code is not None:
        raise SearchAgentFailed(code)  # except 밖에서 던져 요청(머리글)을 든 예외가 따라붙지 않게
    return quotes


async def ask(session: Session, question: str, *, mode: Literal["general", "scholar"] = "general",
              timeout: float = TIMEOUT_S) -> list[AgentQuote]:
    """prepare + call. 받은 세션은 기다리는 동안에도 그대로다 — 오래 기다릴 곳(뒤 작업)은 prepare·call 을 나눠 쓴다.

    부르는 쪽은 commit 하지 않은 쓰기를 쥔 채 부르지 않는다(llm_calls 기록이 잠금을 기다린다).
    """
    return await call(prepare(session), session.get_bind(LlmCall), question, mode=mode, timeout=timeout)
