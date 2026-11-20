from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.store.timeutil import as_utc

Kind = Literal["task", "start_ms", "finish_ms"]
RelType = Literal["FS", "SS", "FF", "SF"]
WeightMode = Literal["duration", "manual"]

# PATCH 에서 null 로 지울 수 있는 칸. 나머지 칸은 null 을 받지 않는다.
CLEARABLE = frozenset({"rd", "actual_start", "actual_finish", "constraint", "manual_weight"})

Days = Annotated[int, Field(ge=0, strict=True)]  # 0 이상 정수(2.0 같은 실수도 받지 않음)
Progress = Annotated[float, Field(ge=0, le=1)]
# 0 이상 수(정수도 받음. 참거짓·글·무한대는 받지 않음)
Weight = Annotated[float, Field(ge=0, strict=True, allow_inf_nan=False)]
# Data Date 로 받는 날짜 범위(조건 날짜와 같은 1900~2199)
DataDate = Annotated[date, Field(ge=date(1900, 1, 1), le=date(2199, 12, 31))]
UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]  # 내보낼 때 +00:00(Z) 이 붙는다


class Strict(BaseModel):
    """모르는 칸은 받지 않는다."""

    model_config = ConfigDict(extra="forbid")


class ConstraintIO(Strict):
    type: Literal["SNET", "FNLT"]
    date: date


class ActivityPatch(Strict):
    """보낸 칸만 바꾼다."""

    name: str | None = None
    kind: Kind | None = None
    wbs: str | None = None
    od: Days | None = None
    rd: Days | None = None
    progress: Progress | None = None
    actual_start: date | None = None
    actual_finish: date | None = None
    constraint: ConstraintIO | None = None
    tags: list[str] | None = None
    resources: list[str] | None = None
    manual_weight: Weight | None = None
    base_version: int

    @model_validator(mode="after")
    def _no_null_on_required(self) -> "ActivityPatch":
        for name in self.model_fields_set - CLEARABLE:
            if getattr(self, name) is None:
                raise ValueError(f"{name} 은(는) 비울 수 없습니다.")
        return self


class ActivityCreate(Strict):
    id: str | None = None
    name: str
    kind: Kind
    wbs: str
    od: Days
    after: str | None = None
    base_version: int


class RelationIn(Strict):
    pred: str
    type: RelType = "FS"
    lag: int = 0


class PredecessorsIn(Strict):
    items: list[RelationIn]
    base_version: int


class RestoreIn(Strict):
    base_version: int


class SchedulePatch(Strict):
    """일정 칸 고치기. 지금은 Data Date 하나(null 이면 지움)."""

    data_date: DataDate | None
    base_version: int


class WeightModeIO(Strict):
    mode: WeightMode


class WbsOut(BaseModel):
    code: str
    name: str
    parent: str | None


class RelationOut(BaseModel):
    pred: str
    succ: str
    type: RelType
    lag: int


class ResourceOut(BaseModel):
    id: str
    name: str
    unit: str
    capacity: int


class ActivityView(BaseModel):
    id: str
    name: str
    kind: Kind
    wbs: str
    od: int
    rd: int | None
    progress: float
    actual_start: date | None
    actual_finish: date | None
    constraint: ConstraintIO | None
    resources: list[str]
    tags: list[str]
    start_floor: date | None = None  # 기록한 지연이 정한 시작 하한
    manual_weight: float | None = None  # 사용자가 넣은 가중치(manual 모드에서 쓴다)
    es: date
    ef: date
    ls: date
    lf: date
    plan_start: date | None
    plan_finish: date | None
    tf: int
    ff: int
    critical: bool
    status: str  # 'done' | 'late +n' | 'early -n' | 'on_plan' | 'new'
    weight: float  # weight_mode 에 따른 공정률 가중치(소수 4자리)


class Summary(BaseModel):
    critical_count: int
    negative_float_count: int
    warning_count: int
    weight_missing: int  # manual 모드에서 가중치를 넣지 않은 task 수(duration 모드는 0)


class BlockedView(BaseModel):
    """작업 금지 기간을 날짜로 펼친 것."""

    tag: str
    start: date
    finish: date


class CalendarView(BaseModel):
    """조건을 넣은 달력. blocked 는 일정 기간(시작 ~ 준공)과 겹치는 것만, 시작일 순."""

    days_per_week: int
    blocked: list[BlockedView]


class DisplayView(BaseModel):
    """그 일정 분야의 표시 설정(분야 묶음의 display, 모르는 분야면 기본값)."""

    gantt_group_by: Literal["wbs", "resource"]
    deadline_label: str
    extra_columns: list[str]


class ScheduleView(BaseModel):
    """계산값을 담은 일정. 날짜는 자원 맞춤까지 마친 값이다."""

    id: int
    name: str
    domain: str
    level: str
    version: int
    data_date: date | None
    finish: date
    plan_finish: date | None  # Plan 이 계산되지 않으면 null
    weight_mode: WeightMode
    display: DisplayView
    calendar: CalendarView
    wbs: list[WbsOut]
    activities: list[ActivityView]
    relations: list[RelationOut]
    resources: list[ResourceOut]
    summary: Summary


class ScheduleItem(BaseModel):
    id: int
    name: str
    domain: str
    level: str
    version: int
    finish: date | None  # 계산이 깨진 일정이면 null
    updated_at: UtcDatetime


class VersionOut(BaseModel):
    n: int
    note: str
    by_kind: str
    by_name: str
    is_plan: bool
    created_at: UtcDatetime
