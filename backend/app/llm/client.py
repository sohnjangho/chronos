"""쓰임새(purpose)에 배정된 모델을 부른다 (OpenAI 호환 Chat Completions).

- 주소·키는 배정이 가리키는 연결에서 읽는다. 키는 Authorization 머리글로만 보내고
  기록(log)·예외·repr·llm_calls 표 어디에도 담지 않는다.
- 다시 시도하지 않는다. 실패는 LlmFailed(설명 붙음)로 바꾼다.
- 호출마다(실패 포함) llm_calls 에 한 줄을 남긴다. 주고받은 글은 남기지 않는다.
"""

import asyncio
import json
import logging
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
# 통신 실패, 시간 초과, 쓸 수 없는 응답(JSON 아님·choices 없음).
_FAILURES = (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError, TypeError, LookupError)


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cost: float | None  # 청구 금액. 응답에 없으면 None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str  # 등록부 이름(점 표기, 예: schedule.read)
    arguments: dict


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


def _json_object(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _tool_calls(message: dict) -> list[ToolCall]:
    calls = []
    for item in message.get("tool_calls") or []:
        function = item["function"]
        arguments = function.get("arguments")
        parsed = _json_object(arguments) if isinstance(arguments, str) else arguments
        calls.append(
            ToolCall(
                id=str(item.get("id", "")),
                name=from_llm_name(function["name"]),
                arguments=parsed if isinstance(parsed, dict) else {},
            )
        )
    return calls


def _parse_reply(data: dict, requested_model: str, *, want_json: bool) -> LlmReply:
    """응답 본문 → LlmReply. choices 가 없으면 LookupError/TypeError (→ 실패로 바뀐다)."""
    message = data["choices"][0]["message"]
    content = message.get("content")
    text = content if isinstance(content, str) else ""
    usage = data.get("usage") or {}
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


class LlmClient:
    def __init__(
        self, session: Session, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._session = session
        self._transport = transport  # 시험에서 httpx.MockTransport 를 넣는다

    def _target(self, purpose: Purpose) -> _Target:
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
        self._session.add(
            LlmCall(
                chat_session_id=chat_session_id,
                purpose=purpose,
                model=reply.model if reply else target.model,
                requested_model=target.model,
                routing_strategy=target.routing_strategy,
                input_tokens=reply.usage.input_tokens if reply else 0,
                output_tokens=reply.usage.output_tokens if reply else 0,
                cost=reply.usage.cost if reply else None,
                latency_ms=latency_ms,
                ok=error is None,
                error_code=error.code if error else None,
            )
        )
        self._session.commit()

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
        """한 번 부른다. 연결이 없으면 LlmNotReady, 실패하면 LlmFailed.

        timeout_s 는 호출 전체에 건다. tools 는 registry.as_llm_tools() 형식.
        json_schema 를 주면 그 모양의 JSON 을 요청하고, 답이 JSON 객체면 reply.parsed 에 담는다
        (아니면 parsed=None, text 에 받은 그대로).
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
