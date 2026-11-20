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
    """text(사용자 글)·questionnaire_id(제출한 질문지로 이어 가기)·approval_id(거부하고 다시 짜게 한 승인 건으로
    이어 가기) 가운데 하나만 보낸다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT)
    ui: UiIn = Field(default_factory=UiIn)
    questionnaire_id: int | None = None
    approval_id: int | None = None

    @model_validator(mode="after")
    def _exactly_one_input(self) -> "MessageIn":
        if sum(x is not None for x in (self.text, self.questionnaire_id, self.approval_id)) != 1:
            raise ValueError("text·questionnaire_id·approval_id 가운데 하나만 보냅니다.")
        return self


class ChatModelIn(BaseModel):
    """이 대화에만 쓸 모델(에이전트 루프의 대화 호출만 바꾼다)."""

    model_config = ConfigDict(extra="forbid")

    connection_id: int
    model: str = Field(min_length=1, max_length=200)
    routing_strategy: Literal["cost", "balanced", "quality"] | None = None


class ChatModelOut(BaseModel):
    connection_id: int
    model: str
    routing_strategy: Literal["cost", "balanced", "quality"] | None


class ChatSessionOut(BaseModel):
    id: int
    title: str  # 첫 사용자 글 40자(질문지로 시작하면 "질문지 답"). 첫 메시지 전에는 빈 글
    schedule_id: int | None
    created_at: datetime


class ChatSessionItem(ChatSessionOut):
    pending_retries: int  # 대화 주인이 시작할 '다시 짜기 요청' 수(아래 RetryOut)


class MessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant", "tool", "event"]
    content: dict  # app/store/chats.py 의 모양. event 는 {"type": card|questionnaire|approval, "data": {...}}
    created_at: datetime


class RetryOut(BaseModel):
    """다른 사람이 '거부하고 다시 짜기' 로 결정해, 대화 주인이 approval_id 로 이어 가기를 기다리는 승인 건."""

    approval_id: int
    title: str
    note: str  # 거부 이유
    decided_by_name: str
    decided_at: datetime


class ChatSessionDetail(ChatSessionOut):
    running: bool  # 지금 턴이 돌고 있는가
    model: ChatModelOut | None  # 이 대화에서 고른 모델. null 이면 설정의 대화 배정(normal)
    messages: list[MessageOut]  # 오래된 것부터 전부
    pending_retries: list[RetryOut]  # 오래된 것부터. 이어 가면(approval_id 로 메시지를 보내면) 빠진다


class StopOut(BaseModel):
    stopping: bool  # 돌고 있던 턴에 멈춤을 표시했으면 true
