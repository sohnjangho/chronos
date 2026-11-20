from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Unit = Literal["week", "month"]
MilestoneStatus = Literal["완료", "예정", "지연", "앞섬"]


class FinishOut(BaseModel):
    current: date
    plan: date | None
    deadline: date | None  # 켜진 finish_by 가운데 가장 이른 날
    delta: int | None  # Plan → 지금 준공의 근무일 수(늦으면 +)
    deadline_float: int | None  # 지금 준공 → 기한의 근무일 수(남으면 +)


class CountsOut(BaseModel):
    total: int
    done: int
    in_progress: int
    late: int


class CurvePointOut(BaseModel):
    date: date
    plan_cum: float
    actual_cum: float | None
    forecast_cum: float | None
    plan_period: float
    actual_period: float | None


class SpiPointOut(BaseModel):
    date: date
    spi: float


class WbsRowOut(BaseModel):
    code: str
    name: str
    weight: float
    plan: float
    actual: float
    diff: float


class MilestoneOut(BaseModel):
    id: str
    name: str
    plan: date | None
    actual_or_forecast: date
    delta: int | None
    status: MilestoneStatus


class DelayOut(BaseModel):
    id: str
    name: str
    delay: int
    tf: int
    finish_impact: int


class DatedOut(BaseModel):
    id: str
    name: str
    date: date


class BlockedOut(BaseModel):
    id: str
    name: str
    date: date
    reason: str


class LookaheadOut(BaseModel):
    from_: date = Field(alias="from")
    to: date
    starts: list[DatedOut]
    finishes: list[DatedOut]
    blocked: list[BlockedOut]


class ComplianceOut(BaseModel):
    pct: int
    done: int
    due: int


class CriticalVarianceOut(BaseModel):
    days: int
    max_id: str


class FinishVarianceOut(BaseModel):
    days: int
    plan: date
    current: date


class CpmOut(BaseModel):
    plan_compliance: ComplianceOut | None
    critical_variance: CriticalVarianceOut | None
    finish_variance: FinishVarianceOut | None


class ProgressOut(BaseModel):
    schedule_id: int
    version: int
    data_date: date
    data_date_assumed: bool
    unit: Unit
    weight_mode: str
    plan_now: float
    actual_now: float
    gap: float
    spi: float | None
    finish: FinishOut
    counts: CountsOut
    curve: list[CurvePointOut]
    spi_trend: list[SpiPointOut]
    wbs: list[WbsRowOut]
    milestones: list[MilestoneOut]
    top_delays: list[DelayOut]
    lookahead: LookaheadOut
    cpm: CpmOut
