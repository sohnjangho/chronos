"""에이전트 루프 시험용 가짜 LLM: 대본대로 답하는 가짜 Liner(ScriptedLlm)와 대본 만들기 도우미.

네트워크를 쓰지 않는다. `LlmClient(session, transport=ScriptedLlm([...]).transport)` 로 쓴다.
"""

import json
from collections.abc import Callable

import httpx

from app.tools.registry import to_llm_name
from tests.llm_doubles import FakeLiner, chat_body, tool_call


class ScriptedLlm(FakeLiner):
    """FakeLiner 에 '요청을 받을 때 부를 함수'(on_request(body))를 더했다."""

    def __init__(self, script=(), *, on_request: Callable[[dict], None] | None = None) -> None:
        super().__init__()
        self.push(*script)
        self.on_request = on_request

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.on_request is not None:
            self.on_request(json.loads(request.content))
        return await super()._handle(request)

    @property
    def last_messages_text(self) -> str:
        """마지막 요청의 모든 메시지 글을 이은 것."""
        return "\n".join(str(m.get("content") or "") for m in self.last_body["messages"])


def reply(text: str, **usage) -> dict:
    """도구 호출 없는 답."""
    return chat_body(text, **usage)


def calls(name: str, arguments: dict, *, text: str | None = None, call_id: str = "call_1", **usage) -> dict:
    """도구 하나를 부르는 답. name 은 등록부 이름(점 표기)."""
    return chat_body(text, tool_calls=[tool_call(to_llm_name(name), arguments, call_id)], **usage)


def raw_call(name: str, raw_arguments: object, call_id: str = "call_1") -> dict:
    """인자 칸을 그대로 넣은 도구 호출 답(깨진 인자·칸 없음 시험용). raw_arguments 가 ... 이면 칸을 뺀다."""
    function: dict = {"name": to_llm_name(name)}
    if raw_arguments is not ...:
        function["arguments"] = raw_arguments
    return chat_body(None, tool_calls=[{"id": call_id, "type": "function", "function": function}])


def FAIL(code: str) -> Exception:
    """가짜 서버가 던질 예외. timeout → LlmFailed(code="timeout")."""
    return {"timeout": TimeoutError(), "connect": httpx.ConnectError("x")}[code]
