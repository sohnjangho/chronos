"""조건·규칙 API 의 요청·응답 모양."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Layer = Literal["base", "domain", "mine", "input"]
State = Literal["passed", "violated", "uncheckable", "off"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditChange(Strict):
    """있는 조건 하나를 바꾼다. params 는 지금 params 에 덮어 합친다."""

    id: str = Field(min_length=1)
    params: dict[str, Any] | None = None
    enabled: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def _something(self) -> "EditChange":
        if self.params is None and self.enabled is None:
            raise ValueError("params 나 enabled 가운데 하나는 보냅니다.")
        return self


class AddChange(Strict):
    """입력 조건 하나를 더한다(Condition.to_dict 모양)."""

    add: dict[str, Any]


class RemoveChange(Strict):
    """입력 조건 하나를 뺀다."""

    remove: str = Field(min_length=1)


Change = EditChange | AddChange | RemoveChange


class ChangesIn(Strict):
    base_version: int
    changes: list[Change] = Field(max_length=100)


class ConditionOut(BaseModel):
    id: str
    layer: Layer
    kind: str
    params: dict[str, Any]
    text: str
    source: str
    enabled: bool
    # False: 못 바꿈 · "toggle": 켜고 끄기만(분야 규칙, 관리자) · True: 값과 켜짐을 바꿈(입력 조건)
    editable: bool | Literal["toggle"]
    state: State
    message: str | None
    overridden_by: str | None
    used_by: list[str] | None  # 이 조건이 걸리는 액티비티(자원·꼬리표·마일스톤 조건만)


class LayersOut(BaseModel):
    base: list[ConditionOut]
    domain: list[ConditionOut]
    mine: list[ConditionOut]
    input: list[ConditionOut]


class SummaryOut(BaseModel):
    passed: int
    violated: int
    uncheckable: int  # 자동 점검하지 않은(못한) 조건. 통과로 세지 않는다


class InvalidOut(BaseModel):
    condition_id: str
    message: str


class ResourceOut(BaseModel):
    id: str
    name: str
    unit: str
    capacity: int


class ConditionsOut(BaseModel):
    schedule_id: int
    name: str
    version: int
    layers: LayersOut
    summary: SummaryOut
    invalid: list[InvalidOut]  # 읽을 수 없는 저장 조건(점검하지 않음)
    resources: list[ResourceOut]


class SideOut(BaseModel):
    finish: date | None  # 계산이 안 되는 저장 버전이면 None
    critical_count: int | None
    violated: int


class Span(BaseModel):
    start: date
    finish: date


class MovedOut(BaseModel):
    activity_id: str
    name: str
    before: Span
    after: Span


class ViolationOut(BaseModel):
    condition_id: str
    message: str
    activity_ids: list[str]
    amount: int | None


class PreviewOut(BaseModel):
    feasible: bool  # 위반이 없으면 참
    view: dict[str, Any]  # 미리 보기 일정(ScheduleView 모양, 저장 안 함)
    before: SideOut
    after: SideOut
    moved: list[MovedOut]
    violations: list[ViolationOut]
    conditions: ConditionsOut  # 미리 보기 상태의 겹(GET 과 같은 모양)


class CommitOut(BaseModel):
    applied: bool  # 바로 반영했는가(false 면 승인함에서 기다린다)
    version: int | None
    approval_id: int


class AskOut(BaseModel):
    chat_session_id: int
    text: str  # 대화 입력창에 미리 넣을 요청 글
