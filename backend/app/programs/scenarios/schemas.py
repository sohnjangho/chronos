from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.store.timeutil import as_utc

UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]  # 내보낼 때 Z 가 붙는다
StatusGroup = Literal["open", "applied", "all"]  # open = open·submitted


class MoveOut(BaseModel):
    id: str
    kind: str  # parallel | compress | add_resource
    text: str


class RecoveryOut(BaseModel):
    planned_gain: int | None  # 단축안을 만들 때 계산한 이득(근무일)
    achieved: int | None  # 지금 준공 → 만들 때 기준 준공(근무일)


class ScenarioOut(BaseModel):
    id: int
    schedule_id: int
    name: str
    source: str  # agent | shorten | delay
    base_version: int
    stale: bool  # 떠 온 버전이 지금 버전이 아님
    status: str  # open | submitted | applied | discarded
    approval_id: int | None
    moves: list[MoveOut]
    delay_event_ids: list[int]
    summary: dict  # store.scenarios.summarize
    created_by: str
    created_at: UtcDatetime
    recovery: RecoveryOut | None = None  # 반영된 단축안(source shorten)만


class ScenarioDetail(ScenarioOut):
    diff: list[dict]  # 지금 일정 대비 바뀌는 액티비티(app.agent.approval.assess 의 diff)


class DiscardOut(BaseModel):
    status: Literal["discarded"]


class SubmitIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=100)  # 없으면 복사본 이름


class SubmitOut(BaseModel):
    approval_id: int
    applied: bool
    status: str  # 복사본의 새 상태: submitted | applied
