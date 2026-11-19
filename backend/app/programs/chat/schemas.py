from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_TEXT = 4000


class ChatSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_id: int | None = None  # 대화가 다룰 일정(없어도 된다)


class UiIn(BaseModel):
    """화면 맥락. 모두 없어도 된다."""

    model_config = ConfigDict(extra="forbid")

    program: str | None = Field(default=None, max_length=50)  # 맨 앞 창의 프로그램 id
    schedule_id: int | None = None  # 그 창이 보여 주는 일정
    selected_activity: str | None = Field(default=None, max_length=50)  # 고른 액티비티 id


class MessageIn(BaseModel):
    """text(사용자 글) 와 questionnaire_id(제출한 질문지로 이어 가기) 가운데 하나만 보낸다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT)
    ui: UiIn = Field(default_factory=UiIn)
    questionnaire_id: int | None = None

    @model_validator(mode="after")
    def _exactly_one_input(self) -> "MessageIn":
        if (self.text is None) == (self.questionnaire_id is None):
            raise ValueError("text 와 questionnaire_id 가운데 하나만 보냅니다.")
        return self


class ChatSessionOut(BaseModel):
    id: int
    title: str  # 첫 사용자 글 40자(질문지로 시작하면 "질문지 답"). 첫 메시지 전에는 빈 글
    schedule_id: int | None
    created_at: datetime


class MessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant", "tool", "event"]
    content: dict  # app/store/chats.py 의 모양. event 는 {"type": card|questionnaire|approval, "data": {...}}
    created_at: datetime


class ChatSessionDetail(ChatSessionOut):
    running: bool  # 지금 턴이 돌고 있는가
    messages: list[MessageOut]  # 오래된 것부터 전부


class StopOut(BaseModel):
    stopping: bool  # 돌고 있던 턴에 멈춤을 표시했으면 true
