"""쓰임새(purpose)에 배정된 모델을 부른다 (OpenAI 호환 Chat Completions).

- 주소·키는 배정이 가리키는 연결에서 읽는다. 키는 Authorization 머리글로만 보내고
  기록(log)·예외·repr·llm_calls 표 어디에도 담지 않는다.
- 다시 시도하지 않는다. 실패는 LlmFailed(설명 붙음)로 바꾼다.
- 호출마다(실패 포함) llm_calls 에 한 줄을 남긴다. 주고받은 글은 남기지 않는다.
  기록은 따로 짧은 세션으로 저장하고, 부른 쪽 세션(트랜잭션)은 건드리지 않는다.
"""

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Literal

import httpx
from sqlalchemy.orm import Session

from app.llm.assignments import Purpose, resolve
from app.llm.connections import secret_is_sendable
from app.llm.errors import LlmError, explain
from app.llm.names import from_llm_name, to_llm_name
from app.security.crypto import SecretUnreadable, decrypt
from app.store.tables import LlmCall, LlmConnection

logger = logging.getLogger(__name__)

NotReadyReason = Literal["no_connection", "secret_unreadable"]
_NOT_READY: dict[str, str] = {
    "no_connection": "LLM 연결이 없습니다. 설정에서 연결을 추가해 주세요.",
    "secret_unreadable": "저장된 키를 읽을 수 없습니다. 키를 다시 넣어 주세요.",
}
# 통신 실패, 시간 초과, 쓸 수 없는 응답(JSON 아님·choices 없음·칸의 모양이 틀림·숫자가 넘침).
_FAILURES = (
    httpx.HTTPError,
    httpx.InvalidURL,
    TimeoutError,
    ValueError,
    TypeError,
    LookupError,
    OverflowError,
)
_MAX_SQL_INT = 2**63 - 1  # SQLite INTEGER 의 가장 큰 값


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cost: float | None  # 청구 금액. 응답에 없으면 None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str  # 등록부 이름(점 표기, 예: schedule.read)
    # 빈 글(공백만 포함)이면 {}(인자 없음). JSON 객체로 읽지 못했으면 None(registry.call 이 거절)
    arguments: dict | None
    raw_arguments: str | None = None  # arguments 가 None 일 때 받은 원문(진단용). 없었으면 None


@dataclass(frozen=True)
class LlmReply:
    text: str
    tool_calls: list[ToolCall]
    model: str  # 실제로 답한 모델
    usage: Usage
    parsed: dict | None = None  # json_schema 를 준 호출에서 답이 JSON 객체일 때만


class LlmNotReady(Exception):
    """부를 수 없다. reason: 'no_connection'(연결 없음) | 'secret_unreadable'(키 다시 넣기)."""

    def __init__(self, reason: NotReadyReason) -> None:
        super().__init__(_NOT_READY[reason])
        self.reason = reason
        self.message = _NOT_READY[reason]


class LlmFailed(Exception):
    """불렀지만 실패했다. error 는 화면에 보여줄 설명."""

    def __init__(self, error: LlmError) -> None:
        super().__init__(error.message)
        self.error = error


@dataclass(frozen=True)
class _Target:
    base_url: str
    model: str
    routing_strategy: str | None
    secret: str = field(repr=False)


def _http_client(transport: httpx.AsyncBaseTransport | None, timeout_s: float) -> httpx.AsyncClient:
    # trust_env=False: 환경 변수의 프록시로 키가 나가지 않게 한다. httpx 는 스스로 다시 시도하지 않는다.
    return httpx.AsyncClient(transport=transport, timeout=timeout_s, trust_env=False)


def _wire_messages(messages: list[dict]) -> list[dict]:
    """대화 기록 속 도구 호출 이름(점 표기)을 LLM 쪽 이름으로 바꾼 사본."""
    out = []
    for message in messages:
        calls = message.get("tool_calls")
        if calls:
            calls = [
                {**c, "function": {**c["function"], "name": to_llm_name(c["function"]["name"])}}
                for c in calls
            ]
            message = {**message, "tool_calls": calls}
        out.append(message)
    return out


def _request_body(
    target: _Target, messages: list[dict], tools: list[dict] | None, json_schema: dict | None
) -> dict:
    body: dict = {"model": target.model, "messages": _wire_messages(messages)}
    if tools:
        body["tools"] = tools
    if json_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "result", "schema": json_schema, "strict": True},
        }
    if target.routing_strategy:
        body["routing_strategy"] = target.routing_strategy
    return body


class _Unusable(ValueError):
    """응답 속 칸의 모양이 틀렸다(→ unknown 실패)."""


def _object(value: object) -> dict:
    """응답 속 객체여야 하는 칸. dict 가 아니면 쓸 수 없는 응답이다."""
    if not isinstance(value, dict):
        raise _Unusable
    return value


def _json_object(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _arguments(raw: object) -> tuple[dict | None, str | None]:
    """(인자, 원문). JSON 객체로 읽히면 (객체, None), 아니면 (None, 받은 원문).

    빈 글이나 공백뿐인 글은 인자 없음({}, None)이다(인자 없는 도구에 ""를 보내는 제공자가 있다).
    """
    if isinstance(raw, dict):
        return raw, None
    if isinstance(raw, str) and not raw.strip():
        return {}, None
    if isinstance(raw, str):
        parsed = _json_object(raw)
        return (parsed, None) if parsed is not None else (None, raw)
    return None, None if raw is None else json.dumps(raw, ensure_ascii=False)


def _tool_calls(message: dict) -> list[ToolCall]:
    calls = []
    for item in message.get("tool_calls") or []:
        function = _object(item["function"])
        name = function["name"]
        if not isinstance(name, str):
            raise _Unusable
        arguments, raw = _arguments(function.get("arguments"))
        calls.append(
            ToolCall(
                id=str(item.get("id", "")),
                name=from_llm_name(name),
                arguments=arguments,
                raw_arguments=raw,
            )
        )
    return calls


def _text(content: object) -> str:
    """답 글. 조각 목록이면 type 이 text 인 조각의 text 를 잇는다(다른 조각은 버린다)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part["text"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        )
    return ""


def _parse_reply(data: dict, requested_model: str, *, want_json: bool) -> LlmReply:
    """응답 본문 → LlmReply.

    모양이 틀리면 ValueError·TypeError·LookupError, 숫자가 넘치면(토큰 수 1e400·Infinity,
    400자리 정수 cost) OverflowError (→ 모두 unknown 실패로 바뀐다).
    """
    message = _object(data["choices"][0]["message"])
    text = _text(message.get("content"))
    usage = data.get("usage")
    usage = {} if usage is None else _object(usage)
    cost = usage.get("cost")
    return LlmReply(
        text=text,
        tool_calls=_tool_calls(message),
        model=str(data.get("model") or requested_model),
        usage=Usage(
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            cost=float(cost) if cost is not None else None,
        ),
        parsed=_json_object(text) if want_json else None,
    )


def _count(n: int) -> int:
    """기록할 토큰 수: 0 ~ SQLite INTEGER 의 가장 큰 값."""
    return min(max(n, 0), _MAX_SQL_INT)


def _money(cost: float | None) -> float | None:
    """기록할 비용: 유한한 값만, 아니면 None."""
    return cost if cost is not None and math.isfinite(cost) else None


def _storable(text: str) -> str:
    """UTF-8 로 쓸 수 없는 글자(짝 없는 surrogate 등)를 '?' 로 바꾼다."""
    return text.encode("utf-8", "replace").decode("utf-8")


class LlmClient:
    """session 은 Engine 에 묶여 있어야 한다. Connection 에 묶인 세션은 지원하지 않는다
    (llm_calls 를 쓰는 기록 세션이 부른 쪽 트랜잭션에 끼게 된다)."""

    def __init__(
        self, session: Session, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._session = session
        self._transport = transport  # 시험에서 httpx.MockTransport 를 넣는다

    def _target(self, purpose: Purpose) -> _Target:
        # 부른 쪽 세션에 쌓인 변경을 flush 하지 않는다. flush 하면 그 연결이 SQLite 쓰기 잠금을
        # 쥐어, 따로 여는 기록 세션이 잠금을 기다리게 된다.
        with self._session.no_autoflush:
            assignment = resolve(self._session, purpose)
            conn = (
                self._session.get(LlmConnection, assignment.connection_id)
                if assignment.connection_id is not None
                else None
            )
        if conn is None:
            raise LlmNotReady("no_connection")
        try:
            secret = decrypt(conn.secret_ciphertext)
        except SecretUnreadable:
            raise LlmNotReady("secret_unreadable") from None
        if not secret_is_sendable(secret):  # 머리글에 실을 수 없는 키는 보내지 않는다
            raise LlmNotReady("secret_unreadable")
        return _Target(
            conn.base_url.rstrip("/"), assignment.model, assignment.routing_strategy, secret
        )

    async def _post(self, target: _Target, body: dict, timeout_s: float) -> dict:
        async with _http_client(self._transport, timeout_s) as http:
            response = await http.post(
                f"{target.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {target.secret}"},
                json=body,
            )
        response.raise_for_status()
        return response.json()

    def _record(
        self,
        purpose: str,
        target: _Target,
        chat_session_id: int | None,
        latency_ms: int,
        reply: LlmReply | None,
        error: LlmError | None,
    ) -> None:
        """llm_calls 한 줄을 LlmCall 의 bind(같은 DB)에 따로 연 짧은 세션으로 저장한다.

        부른 쪽 세션은 commit·expire 하지 않는다. 제공자가 준 값은 쓸 수 있게 다듬는다
        (토큰 수 0~2^63-1, 비용은 유한한 값 아니면 None, 모델 이름의 쓸 수 없는 글자는 '?').
        저장이 어떤 이유로든 실패하면 되돌리고 경고(예외 종류만)를 남길 뿐, 호출 결과는 바꾸지 않는다.
        """
        try:
            row = LlmCall(
                chat_session_id=chat_session_id,
                purpose=purpose,
                model=_storable(reply.model) if reply else target.model,
                requested_model=target.model,
                routing_strategy=target.routing_strategy,
                input_tokens=_count(reply.usage.input_tokens) if reply else 0,
                output_tokens=_count(reply.usage.output_tokens) if reply else 0,
                cost=_money(reply.usage.cost) if reply else None,
                latency_ms=latency_ms,
                ok=error is None,
                error_code=error.code if error else None,
            )
            with Session(self._session.get_bind(LlmCall)) as recorder:
                recorder.add(row)
                try:
                    recorder.commit()
                except Exception:
                    recorder.rollback()
                    raise
        # 기록은 호출 결과(답·LlmFailed)를 바꾸지 않는다. 예외 글·추적에는 SQL 과 값이 들어 있을
        # 수 있으므로 logger.exception 대신 종류만 남긴다(그래서 BLE001 을 끈다).
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 호출 기록 저장 실패: purpose=%s (%s)", purpose, type(exc).__name__)

    async def chat(
        self,
        purpose: Purpose,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        json_schema: dict | None = None,
        timeout_s: float = 60,
        chat_session_id: int | None = None,
    ) -> LlmReply:
        """한 번 부른다. 연결이 없으면 LlmNotReady, 보낸 뒤 실패하면 LlmFailed.

        - timeout_s 는 호출 전체에 건다. tools 는 registry.as_llm_tools() 형식.
        - json_schema 를 주면 strict 모드로 그 모양의 JSON 을 요청한다. strict 모드는 모든 속성이
          required 에 들어 있고 additionalProperties 가 false 여야 하므로(중첩 객체도) 스키마를
          그렇게 써서 넘긴다. 답이 JSON 객체면 reply.parsed 에 담는다(아니면 parsed=None,
          text 에 받은 그대로).
        - reply.tool_calls[].arguments: 빈 글(공백만 포함)이면 {}, JSON 객체가 아닌 글이면 None
          (받은 원문은 raw_arguments). None 인 인자는 registry.call 이 실행하지 않고 거절한다.
        - 없는 purpose(KeyError)·모양이 틀린 messages(KeyError·TypeError·AttributeError)는 부른
          쪽 잘못이다. 보내기 전에 그대로 올라가고 llm_calls 에도 남지 않는다.
        - 기록: 보낸 호출마다(실패 포함) llm_calls 에 한 줄을 남긴다. 받은 세션의 LlmCall bind
          (같은 DB)에 따로 연 짧은 세션으로 저장하고 그것만 commit 한다. 받은 세션은 Engine 에
          묶여 있어야 한다(Connection 에 묶인 세션은 지원하지 않는다: 기록 세션이 부른 쪽
          트랜잭션에 끼게 된다). 받은 세션은 commit·expire·flush 하지 않는다(쌓인 변경도 그대로
          남는다). 기록 저장이 어떤 이유로든 실패해도 경고만 남기고 결과(답 또는 LlmFailed)는
          그대로다. 부르는 쪽은 commit 하지 않은 쓰기를 쥔 채 chat 을 부르면 안
          된다. 그러면 SQLite busy timeout(기본 5초)을 기다린 뒤 사용량 기록이 빠질 수 있다.
        """
        target = self._target(purpose)
        body = _request_body(target, messages, tools, json_schema)
        reply: LlmReply | None = None
        error: LlmError | None = None
        start = time.perf_counter()
        try:
            async with asyncio.timeout(timeout_s):
                data = await self._post(target, body, timeout_s)
            reply = _parse_reply(data, target.model, want_json=json_schema is not None)
        except _FAILURES as exc:
            error = explain(exc)
            # 예외 내용은 남기지 않는다(요청 머리글을 들고 있을 수 있다). 종류만 남긴다.
            logger.warning(
                "LLM 호출 실패: purpose=%s code=%s (%s)", purpose, error.code, type(exc).__name__
            )
        latency_ms = int((time.perf_counter() - start) * 1000)
        self._record(purpose, target, chat_session_id, latency_ms, reply, error)
        if error is not None:
            # except 밖에서 던져 원래 예외(요청 객체를 들고 있다)가 따라붙지 않게 한다.
            raise LlmFailed(error)
        return reply
