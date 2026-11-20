from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VisualKind = Literal["summary", "delay_impact", "scenario_compare", "s_curve", "resource_load"]


class VisualIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: VisualKind
    version: int | None = Field(default=None, ge=1)  # summary·resource_load 는 그 버전, 나머지는 지금 버전이어야 함
    unit: Literal["week", "month"] | None = None  # s_curve 만. 없으면 주(40점이 넘으면 월)


class VisualOut(BaseModel):
    """그림 한 장. html 이 null 이면(fallback) 화면은 rows 로 우리 그림(SVG)을 그리고 note 를 보인다."""

    id: int
    schedule_id: int
    kind: VisualKind
    title: str
    version: int
    data_date: date | None
    columns: list[str]
    rows: list[list[str | int | float | None]]
    chart: Literal["timeline", "bars", "line"]
    html: str | None
    theme: str
    description: str
    resource_id: str
    verified: bool
    passed: int
    total: int
    fallback: bool
    note: str
    external: list[str]  # 받은 HTML 이 부르는 외부 script·link 주소
    latency_ms: int | None
    created_at: datetime
