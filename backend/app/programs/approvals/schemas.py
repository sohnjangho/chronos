from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.store.timeutil import as_utc

Mode = Literal["all", "important", "auto"]  # app.agent.approval.Mode
UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]  # 내보낼 때 Z 가 붙는다
NOTE_LIMIT = 1000


class Strict(BaseModel):
    """모르는 칸은 받지 않는다. 글은 앞뒤 공백을 뗀다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DecideIn(Strict):
    decision: Literal["approve", "reject", "reject_retry"]  # reject_retry = 거부하고 에이전트가 다시 짜게
    note: str = Field(default="", max_length=NOTE_LIMIT)


class DecideOut(BaseModel):
    status: str  # approved | rejected
    version: int | None  # 승인으로 생긴 버전
    schedule_id: int | None  # 대상 일정(첫 저장은 승인으로 생긴 일정)
    chat_session_id: int | None  # 거부하고 다시 짜기면 이 대화에 approval_id 로 이어 간다


class ApprovalOut(BaseModel):
    id: int
    kind: Literal["first_save", "change"]
    title: str
    status: Literal["pending", "approved", "rejected", "conflict", "auto"]
    reasons: list[str]
    schedule_id: int | None
    draft_id: int | None
    base_version: int
    version: int | None
    restore_to: int | None  # 자동 적용을 되돌릴 버전(POST /api/schedules/{id}/versions/{n}/restore)
    retry: bool
    request: str
    chat_session_id: int | None
    requested_by: str
    decided_by: str | None
    note: str
    created_at: UtcDatetime
    decided_at: UtcDatetime | None
    summary: dict  # app.agent.approval.assess 의 summary


class ApprovalDetail(ApprovalOut):
    mode: Mode
    diff: list[dict]  # [{activity_id, name, before: {start, finish} | null, after, finish_delta}]


class ApprovalList(BaseModel):
    mode: Mode
    items: list[ApprovalOut]


class CountOut(BaseModel):
    pending: int


class ModeIO(Strict):
    mode: Mode
