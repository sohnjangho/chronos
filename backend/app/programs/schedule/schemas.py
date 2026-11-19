from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, model_validator

Kind = Literal["task", "start_ms", "finish_ms"]
RelType = Literal["FS", "SS", "FF", "SF"]

# PATCH 에서 null 로 지울 수 있는 칸. 나머지 칸은 null 을 받지 않는다.
CLEARABLE = frozenset({"rd", "actual_start", "actual_finish", "constraint"})


class ConstraintIO(BaseModel):
    type: Literal["SNET", "FNLT"]
    date: date


class ActivityPatch(BaseModel):
    """보낸 칸만 바꾼다."""

    name: str | None = None
    kind: Kind | None = None
    wbs: str | None = None
    od: int | None = None
    rd: int | None = None
    progress: float | None = None
    actual_start: date | None = None
    actual_finish: date | None = None
    constraint: ConstraintIO | None = None
    tags: list[str] | None = None
    resources: list[str] | None = None
    base_version: int

    @model_validator(mode="after")
    def _no_null_on_required(self) -> "ActivityPatch":
        for name in self.model_fields_set - CLEARABLE:
            if getattr(self, name) is None:
                raise ValueError(f"{name} 은(는) 비울 수 없습니다.")
        return self


class ActivityCreate(BaseModel):
    id: str | None = None
    name: str
    kind: Kind
    wbs: str
    od: int
    after: str | None = None
    base_version: int


class RelationIn(BaseModel):
    pred: str
    type: RelType = "FS"
    lag: int = 0


class PredecessorsIn(BaseModel):
    items: list[RelationIn]
    base_version: int


class RestoreIn(BaseModel):
    base_version: int


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
    es: date
    ef: date
    plan_start: date | None
    plan_finish: date | None
    tf: int
    ff: int
    critical: bool
    status: str  # 'done' | 'late +n' | 'early -n' | 'on_plan' | 'new'
    weight: float


class Summary(BaseModel):
    critical_count: int
    negative_float_count: int
    warning_count: int


class ScheduleView(BaseModel):
    """계산값을 담은 일정. 날짜는 자원 맞춤까지 마친 값이다."""

    id: int
    name: str
    domain: str
    level: str
    version: int
    data_date: date | None
    finish: date
    plan_finish: date
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
    updated_at: datetime


class VersionOut(BaseModel):
    n: int
    note: str
    by_kind: str
    by_name: str
    is_plan: bool
    created_at: datetime
