"""에이전트가 화면으로 내보내는 사건 하나와, 그것을 SSE 글로 바꾸는 방법."""

import json
from dataclasses import dataclass
from typing import Literal

EventType = Literal[
    "text",
    "tool_start",
    "tool_end",
    "card",
    "workflow",
    "open_window",
    "questionnaire",
    "approval",
    "usage",
    "error",
    "done",
]


@dataclass(frozen=True)
class AgentEvent:
    type: EventType
    data: dict


def json_safe(value: object) -> object:
    """글자 안의 짝 없는 서로게이트(UTF-8 로 쓸 수 없는 글자)를 '?' 로 바꾼 사본. dict 의 열쇠·목록 속도 바꾼다.

    LLM 이 준 글(답·모델 이름·도구 이름·인자)을 화면으로 보내거나 DB 에 넣기 전에 늘 이것을 거친다.
    """
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, dict):
        return {json_safe(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    return value


def to_sse(event: AgentEvent) -> str:
    """`event: <type>\\ndata: <json>\\n\\n`. data 는 한 줄 JSON(json_safe 를 거침)."""
    data = json.dumps(json_safe(event.data), ensure_ascii=False)
    return f"event: {event.type}\ndata: {data}\n\n"
