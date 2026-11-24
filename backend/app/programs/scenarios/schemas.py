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


class SideOut(BaseModel):
    """비교판의 한 안(app.programs.scenarios.compare). 날짜 차이는 이 안의 조건 넣은 달력의 근무일."""

    ref: str  # current | plan | v:<n> | s:<복사본 id>
    label: str  # "현재 일정 (버전 n)" · "Plan (버전 n)" · "버전 n" · 복사본 이름
    version: int  # 그 버전(복사본은 떠 온 버전)
    finish: str  # YYYY-MM-DD
    plan_delta: int | None  # Plan 준공 → 이 안 준공. Plan 이 계산되지 않으면 None
    deadline: str | None  # 켜진 finish_by 가운데 가장 이른 기한(YYYY-MM-DD, 코드 계산). 없으면 None
    deadline_float: int | None  # 이 안 준공 → 가장 이른 켜진 finish_by(없으면 None, 늦으면 음수)
    critical_count: int
    violations: int  # 조건 위반 수
    uncheckable: int  # 자동 점검 안 된 조건 수
    peak: dict | None  # {resource_id, name, need, capacity, when} · 쓰는 자원이 없으면 None
    changes: list[str]  # 복사본은 이동 글, 버전은 note
    stale: bool  # 복사본이 떠 온 버전이 지금 버전이 아님
    status: str | None  # 복사본의 상태(open·submitted·applied·discarded). 복사본이 아니면 None
    # 만회안의 당김 효과 {pulled_days, finish_gain, warn, next_chain: [{activity_id, name, point}]}
    # — 「준공 반영」 finish_gain/pulled_days 일, 「다음 결정 줄」. 만회안·만약에 복사본이 아니면 None
    accel: dict | None = None
    accel_reason: str | None = None  # 만약에 복사본이 여러 가지를 함께 바꿔 당김 효과를 셀 수 없을 때의 까닭


class RowCell(BaseModel):
    start: str
    finish: str
    od: int


class RowOut(BaseModel):
    activity_id: str
    name: str
    wbs: str
    base: RowCell | None  # 기준에 없으면 None
    other: RowCell | None  # 비교에 없으면 None
    start_delta: int | None  # 근무일(기준 쪽 달력), other − base. 한쪽에만 있으면 None
    finish_delta: int | None
    change: Literal["pulled", "pushed", "same", "added", "removed", "duration"]


class CompareOut(BaseModel):
    base: SideOut
    other: SideOut
    rows: list[RowOut]  # 기준 차례, 다음 비교에만 있는 것
    changed_count: int  # change 가 same 이 아닌 줄 수


class CompareSummaryOut(BaseModel):
    sides: list[SideOut]  # 현재 · Plan · 열린(open·submitted) 복사본 새것부터
