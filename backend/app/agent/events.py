"""에이전트가 화면으로 내보내는 사건 하나."""

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
