"""시험·시연 전용 가짜 Liner. 네트워크를 쓰지 않고 정해진 대본대로만 답한다.

환경 변수 CHRONOS_FAKE_LLM 이 정확히 "1" 일 때만 `LlmClient` 의 기본 transport 가 된다(기본은 꺼짐).
꺼져 있으면 `transport()` 가 RuntimeError 를 내므로 가짜를 만들 수조차 없다. PM 앱에는 켜지 않는다.
**바꾸는 것은 `LlmClient` 의 Chat Completions 뿐이다.** 근거 검색(search.py)·MCP(mcp_client.py)·연결 시험(llm_settings)·
Liner 시각화(visualization.py)는 따로 부르므로, 불리면 그대로 밖(Liner)으로 나간다.

대본(화면 끝에서 끝까지 시험 `frontend/e2e/demo.spec.ts`·`bundle2.spec.ts` 와 서버 시험 `tests/e2e/` 의 범위만).
턴 = 마지막 사용자 글과 그 뒤의 도구 호출. 위에서부터 맞는 첫 줄:
- 단축안 설명 요청(json_schema 에 recommended·notes) → 안마다 짧은 설명, 추천은 null(코드 추천이 고른다).
- 사용자 글에 "만회" → shorten.make(글에 "n일"이 있으면 target_days) → 끝나면 글 한 줄(도구가 실패했으면 그 까닭).
- 사용자 글에 "늦어졌"·"밀렸" → schedule.find(화면에서 고른 액티비티, 없으면 "골조") → 찾은 첫 액티비티로
  delay.record(일수 = 글의 "n일", 원인 = "○ 때문에" 의 ○, 책임은 말하지 않았으니 undecided) → 끝나면 글 한 줄
  (기록이 실패했으면 기록했다고 하지 않고 그 까닭).
- 도구 호출이 아직 없는 대화의 첫 요청이고 ask.questionnaire 도구를 받았으면 → 일정 질문지(질문 셋)를 연다.
- 그 밖에는 → 짧은 글 한 줄(도구를 부르지 않는다).
Search·MCP·시각화·날씨는 부르지 않는 대본이다.
"""

import json
import os
import re

import httpx

from app.llm.names import to_llm_name

ENV = "CHRONOS_FAKE_LLM"
MODEL = "fake-liner"
_ASK = to_llm_name("ask.questionnaire")
_FIND, _DELAY, _SHORTEN = (to_llm_name(n) for n in ("schedule.find", "delay.record", "shorten.make"))
DONE_TEXT = "질문지를 열었습니다. 답을 채워 제출해 주세요. (시연용 가짜 LLM)"
TALK_TEXT = "시연용 가짜 LLM 입니다. 실제 답은 Liner 연결로 받습니다."
DELAY_DONE_TEXT = "지연을 기록했습니다. 준공 영향은 카드와 지연 기록 창에서 확인하세요. (시연용 가짜 LLM)"
NOT_FOUND_TEXT = "말씀하신 작업을 일정에서 찾지 못했습니다. 작업 이름이나 ID 를 알려 주세요. (시연용 가짜 LLM)"
RECOVERY_DONE_TEXT = "만회안을 만들었습니다. 비교판에서 안을 비교하고 [이 안을 반영]으로 승인함에 올리세요. (시연용 가짜 LLM)"
NOTE_TEXT = "바꾸는 것 {n}가지. 시연용 가짜 LLM 설명입니다."
FAILED_TEXT = "{what} 못했습니다: {error} (시연용 가짜 LLM)"
_SELECTED = re.compile(r"고른 액티비티: (\S+)")
_DAYS = re.compile(r"(\d+)\s*일")
_CAUSE = re.compile(r"(\S+)\s*때문에")


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


def _call(name: str, args: dict, messages: list[dict]) -> dict:
    """도구 호출 하나. 호출 id 는 대화 안에서 겹치지 않게 지금까지의 호출 수로 붙인다."""
    n = sum(len(m.get("tool_calls") or []) for m in messages) + 1
    return _body(None, [{"id": f"fake_call_{n}", "type": "function",
                         "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}])


def _turn(messages: list[dict]) -> tuple[str, list[tuple[str, str]]]:
    """(마지막 사용자 글, 그 뒤 도구 호출의 [(이름, 결과 글)] 차례)."""
    last = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    text = (messages[last].get("content") or "") if last >= 0 else ""
    results = {m.get("tool_call_id"): m.get("content") or "" for m in messages[last + 1:] if m.get("role") == "tool"}
    calls = [(c["function"]["name"], results.get(c["id"], ""))
             for m in messages[last + 1:] if m.get("role") == "assistant" for c in m.get("tool_calls") or []]
    return (text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)), calls


def _notes(request: dict) -> dict | None:
    """단축안 설명 요청이면 그 답(설명만, 날짜 없음). 아니면 None."""
    schema = ((request.get("response_format") or {}).get("json_schema") or {}).get("schema") or {}
    if not {"recommended", "notes"} <= set(schema.get("properties") or {}):
        return None
    options = json.loads(_turn(request.get("messages", []))[0] or "[]")
    notes = [{"key": o["key"], "note": NOTE_TEXT.format(n=len(o.get("moves") or []))} for o in options]
    return _body(json.dumps({"recommended": None, "notes": notes}, ensure_ascii=False))


def _error_of(result: str) -> str | None:
    """도구 결과가 실패({"error": …})면 그 글. 아니면 None."""
    try:
        data = json.loads(result)
    except ValueError:
        return None
    return str(data["error"]) if isinstance(data, dict) and data.get("error") else None


def _first_match(result: str) -> str | None:
    try:
        matches = json.loads(result).get("matches") or []
    except (ValueError, AttributeError):
        return None
    return matches[0]["id"] if matches else None


def _delay(text: str, calls: list[tuple[str, str]], messages: list[dict]) -> dict:
    """지연을 말한 턴: 찾기 → 기록 → 글."""
    if not calls:
        selected = next((m.group(1) for msg in messages if isinstance(msg.get("content"), str)
                         for m in [_SELECTED.search(msg["content"])] if m), None)
        return _call(_FIND, {"query": selected or "골조"}, messages)
    name, result = calls[-1]
    if name == _FIND and (activity := _first_match(result)):
        days = _DAYS.search(text)
        cause = _CAUSE.search(text)
        return _call(_DELAY, {"activity_id": activity, "days": int(days.group(1)) if days else 1,
                              "cause": cause.group(1) if cause else "대화에서 말한 지연"}, messages)
    if name == _DELAY and (error := _error_of(result)):
        return _body(FAILED_TEXT.format(what="지연을 기록하지", error=error))
    return _body(DELAY_DONE_TEXT if name == _DELAY else NOT_FOUND_TEXT)


def _recovery(text: str, calls: list[tuple[str, str]], messages: list[dict]) -> dict:
    """만회를 말한 턴: 단축안 → 글."""
    if calls:
        error = _error_of(calls[-1][1])
        return _body(FAILED_TEXT.format(what="만회안을 만들지", error=error) if error else RECOVERY_DONE_TEXT)
    days = _DAYS.search(text)
    return _call(_SHORTEN, {"target_days": int(days.group(1))} if days else {}, messages)


def answer(request: dict) -> dict:
    """요청 본문(Chat Completions) → 응답 본문. 같은 요청에는 늘 같은 답."""
    if (notes := _notes(request)) is not None:
        return notes
    offered = {t.get("function", {}).get("name") for t in request.get("tools") or []}
    messages = request.get("messages", [])
    text, calls = _turn(messages)
    if "만회" in text and _SHORTEN in offered:
        return _recovery(text, calls, messages)
    if ("늦어졌" in text or "밀렸" in text) and _FIND in offered:
        return _delay(text, calls, messages)
    called_before = any(m.get("tool_calls") for m in messages)
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
