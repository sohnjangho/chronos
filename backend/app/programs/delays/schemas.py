from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.store.timeutil import as_utc

UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]  # 내보낼 때 Z 가 붙는다
Responsibility = Literal["owner", "ours", "force", "undecided"]  # 발주처·우리·불가항력·정하지 않음
Days = Annotated[int, Field(ge=1, le=365)]
Cause = Annotated[str, Field(min_length=1, max_length=200)]
Cost = Annotated[int, Field(ge=0)]  # 하루 금액(원)
Evidence = Annotated[str, Field(max_length=200)]
CLEARABLE = {"daily_cost"}  # PATCH 로 null 을 보내 비울 수 있는 칸


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DelayIn(Strict):
    activity_id: str = Field(min_length=1, max_length=50)
    start_date: date
    days: Days
    cause: Cause
    responsibility: Responsibility = "undecided"
    daily_cost: Cost | None = None
    evidence: Evidence = ""


class DelayPatch(Strict):
    """보낸 칸만 바꾼다."""

    activity_id: str | None = Field(default=None, min_length=1, max_length=50)
    start_date: date | None = None
    days: Days | None = None
    cause: Cause | None = None
    responsibility: Responsibility | None = None
    daily_cost: Cost | None = None
    evidence: Evidence | None = None

    @model_validator(mode="after")
    def _no_null_on_required(self) -> "DelayPatch":
        for name in self.model_fields_set - CLEARABLE:
            if getattr(self, name) is None:
                raise ValueError(f"{name} 은(는) 비울 수 없습니다.")
        return self


class ScenarioIn(Strict):
    event_ids: list[int] | None = None  # 없으면 열린 사건 모두


class MilestoneOut(BaseModel):
    activity_id: str
    name: str
    before: date
    after: date
    delta: int  # 근무일


class ClashOut(BaseModel):
    resource_id: str
    name: str
    first: date
    days: int
    over: int


class ImpactOut(BaseModel):
    applied: bool  # 일정에 넣었는가(끝난 액티비티·마일스톤·없는 액티비티면 false, 까닭은 note)
    note: str | None
    finish_before: date
    finish_after: date
    finish_delta: int  # 근무일
    absorbed: int  # 여유로 흡수된 근무일
    milestones: list[MilestoneOut]
    critical_added: list[str]
    critical_removed: list[str]
    affected: list[str]
    new_clashes: list[ClashOut]
    cost: int | None  # finish_delta × 하루 금액(하루 금액이 없으면 null)


class DelayOut(BaseModel):
    id: int
    activity_id: str
    activity_name: str
    start_date: date
    days: int
    cause: str
    responsibility: str
    daily_cost: int | None
    evidence: str
    source: str  # user | chat | actual
    status: str  # open | reflected
    impact: ImpactOut | None
    analyzed_version: int | None
    reflected_version: int | None
    stale: bool  # 열린 사건인데 지금 버전으로 분석하지 않음
    created_by: str
    created_at: UtcDatetime


class ByResponsibility(BaseModel):
    owner: int
    ours: int
    force: int
    undecided: int


class TotalsOut(BaseModel):
    finish_impact: int  # 사건들이 준공을 민 근무일의 합(열림·반영 모두)
    by_responsibility: ByResponsibility
    absorbed: int
    absorbed_events: int
    cost: int | None
    open_count: int


class FinishOut(BaseModel):
    plan: date | None  # Plan: 지금 버전을 실적·기록한 지연 없이 계산한 준공(지연은 Plan 을 옮기지 않는다)
    current: date  # 지금 버전(반영된 지연 포함)
    with_open: date  # 열린 사건까지 넣은 준공
    deadline: date | None
    deadline_float: int | None  # 근무일(with_open → deadline), 늦으면 음수


class DelaysOut(BaseModel):
    schedule_id: int
    version: int
    events: list[DelayOut]
    totals: TotalsOut
    finish: FinishOut


class MovedSpan(BaseModel):
    start: date
    finish: date


class MovedOut(BaseModel):
    activity_id: str
    name: str
    before: MovedSpan
    after: MovedSpan


class PreviewOut(BaseModel):
    view: dict[str, Any]  # 열린 사건을 넣은 일정(ScheduleView 모양, 저장 안 함)
    moved: list[MovedOut]


class ScenarioOut(BaseModel):
    scenario_id: int
