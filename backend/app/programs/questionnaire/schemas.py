from typing import Literal

from pydantic import BaseModel

from app.store.questionnaires import (
    AssumedAnswer,
    Prefilled,
    QuestionOption,
    SubmittedAnswer,
)


class AnswerIn(BaseModel):
    question_id: str
    value: str | None  # null 이면 답을 지운다


class AnswerOut(BaseModel):
    value: str
    label: str  # 선택지의 label, 직접 적은 답이면 그 글


class QuestionOut(BaseModel):
    id: str
    question: str
    why: str
    options: list[QuestionOption]
    allow_free: bool
    assumption: str  # 답하지 않으면 이렇게 가정한다
    answer: AnswerOut | None


class GroupOut(BaseModel):
    name: str
    answered: int
    total: int
    questions: list[QuestionOut]


class Progress(BaseModel):
    answered: int
    total: int


class QuestionnaireView(BaseModel):
    id: int
    title: str
    purpose: str
    status: Literal["open", "submitted"]
    round: int
    progress: Progress
    prefilled: list[Prefilled]
    groups: list[GroupOut]  # 질문에 처음 나온 차례


class SubmitOut(BaseModel):
    id: int
    status: Literal["submitted"]
    answers: list[SubmittedAnswer]
    assumed: list[AssumedAnswer]
