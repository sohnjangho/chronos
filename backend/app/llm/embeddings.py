"""임베딩: 「임베딩」(embedding) 배정의 연결로 `POST {base_url}/embeddings`(OpenAI 호환)를 부른다.

- 모델은 배정 모델. 다시 넣기 중 검색처럼 다른 모델이 필요하면 model 로 준다(연결은 배정 그대로).
- BATCH 개씩 묶어 보낸다. 글 하나는 그 모델 context_length(토큰, 모르면 8192)의 절반 글자까지만 넣는다 — 넘으면
  앞부분만 넣고 기록(log)에 적는다(실측 한국어 약 1.2 토큰/자, 넉넉히 2 토큰/자로 본다).
- 키는 Authorization 머리글로만 보낸다. 기록·예외·llm_calls 어디에도 담지 않는다. 다시 시도하지 않는다(files.jobs 가 한다).
  실패는 EmbedFailed(code) — code 는 근거 검색(Task 27)과 같은 이름에 연결 문제 둘(no_connection·secret_unreadable).
- 호출마다(실패 포함) llm_calls 에 한 줄(purpose embedding, 입력 토큰·비용). LlmClient 의 연결 풀기·기록을 그대로 쓴다.
- CHRONOS_FAKE_LLM=1 이면 가짜 Liner 로 보낸다(대화만 아는 가짜라 unknown 실패 — 밖으로 나가지 않는다).
"""

import asyncio
import logging
import math
import time
from dataclasses import replace

import httpx
from sqlalchemy.orm import Session

from app.llm import fake
from app.llm.assignments import resolve
from app.llm.client import LlmClient, LlmNotReady, LlmReply, Usage, _Target
from app.llm.errors import LlmError
from app.store.tables import LlmConnection

logger = logging.getLogger(__name__)

BATCH = 64
DEFAULT_CONTEXT = 8192  # 토큰. 실측 openai/text-embedding-3-small 의 context_length
# 시험이 가짜 transport 를 바꿔 끼운다. None 이면 CHRONOS_FAKE_LLM=1 일 때 가짜 Liner, 아니면 실제 Liner.
TRANSPORT: httpx.AsyncBaseTransport | None = None

MESSAGES = {
    "bad_request": "임베딩 요청 형식이 맞지 않습니다.",
    "bad_key": "API 키가 맞지 않습니다.",
    "no_credit": "Liner 크레딧이 부족합니다.",
    "rate_limited": "호출 한도를 넘었습니다. 잠시 뒤 다시 해 주세요.",
    "server_error": "임베딩 서버에 문제가 생겼습니다.",
    "timeout": "응답이 너무 늦습니다.",
    "bad_url": "주소에 연결할 수 없습니다.",
    "unknown": "임베딩 결과를 읽지 못했습니다.",
    "no_connection": "임베딩에 쓸 LLM 연결이 없습니다. 설정에서 연결해 주세요.",
    "secret_unreadable": "저장된 키를 읽을 수 없습니다. 키를 다시 넣어 주세요.",
}
_STATUS_CODES = {400: "bad_request", 401: "bad_key", 402: "no_credit", 403: "bad_key", 404: "bad_url", 429: "rate_limited"}
_SERVER_ERROR_FROM = 500
# 통신 실패·시간 초과·쓸 수 없는 응답(JSON 아님·data 없음·벡터 수나 차원이 맞지 않음·숫자가 아님)
_FAILURES = (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError, TypeError, LookupError, OverflowError)


class EmbedFailed(Exception):
    """임베딩하지 못했다. code 는 MESSAGES 의 열쇠, message 는 화면에 보일 설명."""

    def __init__(self, code: str) -> None:
        super().__init__(MESSAGES[code])
        self.code = code
        self.message = MESSAGES[code]


class _Unusable(ValueError):
    """200 이지만 벡터를 쓸 수 없다(→ unknown)."""


def _code(exc: BaseException) -> str:
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return "server_error" if status >= _SERVER_ERROR_FROM else _STATUS_CODES.get(status, "unknown")
    if isinstance(exc, httpx.InvalidURL | httpx.UnsupportedProtocol | httpx.ConnectError):
        return "bad_url"
    return "unknown"


def _max_chars(session: Session, model: str) -> int:
    """글 하나에 넣을 글자 수: 연결의 모델 목록에 적힌 context_length(없으면 DEFAULT_CONTEXT)의 절반."""
    with session.no_autoflush:
        assignment = resolve(session, "embedding")
        conn = session.get(LlmConnection, assignment.connection_id) if assignment.connection_id is not None else None
    for item in (conn.models_json if conn is not None else None) or []:
        if isinstance(item, dict) and item.get("id") == model:
            context = item.get("context_length")
            if isinstance(context, int) and not isinstance(context, bool) and context > 0:
                return context // 2
    return DEFAULT_CONTEXT // 2


def _cut(text: str, index: int, limit: int) -> str:
    if len(text) <= limit:
        return text
    logger.info("임베딩: %d번째 글이 길어 앞 %d자만 넣습니다(원래 %d자)", index + 1, limit, len(text))
    return text[:limit]


def _parse(data: object, requested_model: str, count: int) -> tuple[list[list[float]], LlmReply]:
    """응답 → (index 차례의 벡터들, 기록용 LlmReply). 수·차원이 맞지 않거나 숫자가 아니면 _Unusable 등."""
    rows = sorted(data["data"], key=lambda row: row["index"])
    found = [[float(x) for x in row["embedding"]] for row in rows]
    dim = len(found[0]) if found else 0
    if len(found) != count or dim == 0 or any(len(v) != dim or not all(map(math.isfinite, v)) for v in found):
        raise _Unusable
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        raise _Unusable
    cost = usage.get("cost")
    tokens = int(usage.get("prompt_tokens") or 0)
    reply = LlmReply(text="", tool_calls=[], model=str(data.get("model") or requested_model),
                     usage=Usage(tokens, 0, float(cost) if cost is not None else None))
    return found, reply


async def _send(
    client: LlmClient, http: httpx.AsyncClient, target: _Target, batch: list[str], timeout_s: float
) -> list[list[float]]:
    found: list[list[float]] = []
    reply: LlmReply | None = None
    code: str | None = None
    start = time.perf_counter()
    try:
        async with asyncio.timeout(timeout_s):
            response = await http.post(f"{target.base_url}/embeddings",
                                       headers={"Authorization": f"Bearer {target.secret}"},
                                       json={"model": target.model, "input": batch})
        response.raise_for_status()
        found, reply = _parse(response.json(), target.model, len(batch))
    except _FAILURES as exc:
        code = _code(exc)
        # 예외 내용은 남기지 않는다(요청 머리글을 들고 있을 수 있다). 종류만 남긴다.
        logger.warning("임베딩 실패: model=%s code=%s (%s)", target.model, code, type(exc).__name__)
    error = LlmError(code, MESSAGES[code]) if code is not None else None
    client._record("embedding", target, None, int((time.perf_counter() - start) * 1000), reply, error)
    if code is not None:
        # except 밖에서 던져 원래 예외(요청 객체를 들고 있다)가 따라붙지 않게 한다.
        raise EmbedFailed(code)
    return found


async def embed(
    session: Session, texts: list[str], *, model: str | None = None, timeout_s: float = 60
) -> list[list[float]]:
    """글마다 벡터 하나(같은 차례). 부를 수 없거나 실패하면 EmbedFailed. 받은 세션은 읽기만 한다.

    timeout_s 는 묶음 한 번에 건다. 부르는 쪽은 commit 하지 않은 쓰기를 쥔 채 부르지 않는다(llm_calls 기록이 잠금을 기다린다).
    """
    if not texts:
        return []
    client = LlmClient(session)
    try:
        target = client._target("embedding")
    except LlmNotReady as exc:
        raise EmbedFailed(exc.reason) from None
    if model:
        target = replace(target, model=model)
    limit = _max_chars(session, target.model)
    inputs = [_cut(text, i, limit) for i, text in enumerate(texts)]
    transport = TRANSPORT if TRANSPORT is not None else (fake.transport() if fake.enabled() else None)
    found: list[list[float]] = []
    # trust_env=False: 환경 변수의 프록시로 키가 나가지 않게 한다. httpx 는 스스로 다시 시도하지 않는다.
    async with httpx.AsyncClient(transport=transport, timeout=timeout_s, trust_env=False) as http:
        for start in range(0, len(inputs), BATCH):
            found.extend(await _send(client, http, target, inputs[start:start + BATCH], timeout_s))
    return found
