"""시험·시연 전용 가짜 Liner. 네트워크를 쓰지 않고 정해진 대본대로만 답한다.

환경 변수 CHRONOS_FAKE_LLM 이 정확히 "1" 일 때만 `LlmClient` 의 기본 transport 가 된다(기본은 꺼짐).
꺼져 있으면 `transport()` 가 RuntimeError 를 내므로 가짜를 만들 수조차 없다. PM 앱에는 켜지 않는다.

대본(화면 끝에서 끝까지 시험 `frontend/e2e/demo.spec.ts` 의 범위만):
- 도구 호출이 아직 없는 대화의 첫 요청이고 ask.questionnaire 도구를 받았으면 → 일정 질문지(질문 셋)를 연다.
- 그 밖에는 → 짧은 글 한 줄(도구를 부르지 않는다).
"""

import json
import os

import httpx

from app.llm.names import to_llm_name

ENV = "CHRONOS_FAKE_LLM"
MODEL = "fake-liner"
_ASK = to_llm_name("ask.questionnaire")
DONE_TEXT = "질문지를 열었습니다. 답을 채워 제출해 주세요. (시연용 가짜 LLM)"
TALK_TEXT = "시연용 가짜 LLM 입니다. 실제 답은 Liner 연결로 받습니다."


def _option(value: str, label: str, recommended: bool = False) -> dict:
    return {"value": value, "label": label, "hint": None, "recommended": recommended}


DEMO_QUESTIONNAIRE = {
    "purpose": "generate",
    "title": "5층 사무동 일정 질문지",
    "domain": "construction",
    "level": "L3",
    "questions": [
        {"id": "structure", "group": "범위", "question": "건물의 구조 형식은 무엇인가요?",
         "why": "층당 골조 기간이 구조 형식에 따라 달라집니다.",
         "options": [_option("rc", "철근콘크리트", True), _option("steel", "철골")],
         "allow_free": True, "assumption": "철근콘크리트 구조로 가정합니다."},
        {"id": "basement", "group": "범위", "question": "지하층이 있나요?", "why": "터파기 기간이 달라집니다.",
         "options": [_option("0", "없음", True), _option("1", "지하 1층")],
         "allow_free": False, "assumption": "지하층이 없다고 가정합니다."},
        {"id": "tower_crane", "group": "자원", "question": "타워크레인은 몇 대인가요?",
         "why": "골조·외장 작업이 크레인을 함께 씁니다.",
         "options": [_option("1", "1대", True), _option("2", "2대")],
         "allow_free": True, "assumption": "타워크레인 1대로 가정합니다."},
    ],
    "prefilled": [{"label": "분야", "value": "건설", "source": "프롬프트"}],
}


def enabled() -> bool:
    return os.environ.get(ENV) == "1"


def _body(text: str | None, tool_calls: list[dict] | None = None) -> dict:
    message: dict = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    choice = {"index": 0, "message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}
    return {"model": MODEL, "choices": [choice], "usage": {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0}}


def answer(request: dict) -> dict:
    """요청 본문(Chat Completions) → 응답 본문. 같은 요청에는 늘 같은 답."""
    offered = {t.get("function", {}).get("name") for t in request.get("tools") or []}
    called_before = any(m.get("tool_calls") for m in request.get("messages", []))
    if _ASK in offered and not called_before:
        call = {"id": "fake_call_1", "type": "function",
                "function": {"name": _ASK, "arguments": json.dumps(DEMO_QUESTIONNAIRE, ensure_ascii=False)}}
        return _body(None, [call])
    return _body(DONE_TEXT if called_before else TALK_TEXT)


def _handle(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=answer(json.loads(request.content)))


def transport() -> httpx.MockTransport:
    if not enabled():
        raise RuntimeError(f"{ENV}=1 이 아니면 가짜 LLM 을 쓸 수 없습니다.")
    return httpx.MockTransport(_handle)
