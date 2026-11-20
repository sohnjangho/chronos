"""LLM 시험용 가짜: 대본대로 답하는 가짜 Liner 서버와 연결 만들기 도우미.

네트워크를 쓰지 않는다. `LlmClient(session, transport=FakeLiner().transport)` 로 쓴다.
"""

import asyncio
import json

import httpx

from app.security.crypto import encrypt
from app.store.tables import LlmConnection

LINER = "https://platform.liner.com/api/v1"
KEY = "sk-test-KEY-abcd1234efgh5678"


def chat_body(
    text: str | None = "ok",
    *,
    tool_calls: list[dict] | None = None,
    model: str = "claude-opus-5.5",
    prompt_tokens: int = 12,
    completion_tokens: int = 5,
    cost: float | None = 0.04,
    finish_reason: str | None = None,
) -> dict:
    """OpenAI Chat Completions 응답 본문. cost=None 이면 usage.cost 를, finish_reason=None 이면 그 칸을 뺀다."""
    message: dict = {"role": "assistant", "content": text}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    usage: dict = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
    if cost is not None:
        usage["cost"] = cost
    choice: dict = {"index": 0, "message": message}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return {"model": model, "choices": [choice], "usage": usage}


def tool_call(llm_name: str, arguments: dict, call_id: str = "call_1") -> dict:
    """응답에 넣을 도구 호출 하나. llm_name 은 LLM 쪽 이름(예: schedule__read)."""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": llm_name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


class FakeLiner:
    """대본(push)에 쌓은 차례대로 답한다. 대본이 비면 chat_body() 를 준다.

    push 에 넣을 수 있는 것: 응답 본문 dict · httpx.Response · 던질 예외.
    delay_s 를 주면 답하기 전에 그만큼 기다린다(시간 초과 시험).
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict] = []
        self.delay_s = 0.0
        self._script: list[dict | httpx.Response | Exception] = []

    def push(self, *items: dict | httpx.Response | Exception) -> None:
        self._script.extend(items)

    @property
    def last_body(self) -> dict:
        return self.bodies[-1]

    @property
    def last_request(self) -> httpx.Request:
        return self.requests[-1]

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.bodies.append(json.loads(request.content))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        item = self._script.pop(0) if self._script else chat_body()
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=item)


def add_connection(
    session, *, name: str = "Liner 기본", base_url: str = LINER, secret: str = KEY,
    is_default: bool = True,
) -> LlmConnection:
    """연결 한 줄을 바로 DB에 넣는다(연결 시험 없이). 키는 암호문으로 들어간다."""
    conn = LlmConnection(
        name=name,
        provider="liner",
        base_url=base_url,
        secret_ciphertext=encrypt(secret),
        secret_last4=secret[-4:],
        is_default=is_default,
        status="ok",
    )
    session.add(conn)
    session.commit()
    return conn
