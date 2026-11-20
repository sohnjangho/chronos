from datetime import date
from typing import Literal

from pydantic import BaseModel


class AttentionItem(BaseModel):
    id: int
    name: str
    domain: str
    finish: date | None  # 계산이 안 되는 일정은 None
    plan_finish: date | None
    finish_delta: int | None  # 준공이 Plan 보다 늦은 근무일(앞서면 음수). Plan 이 없으면 None
    late_count: int
    negative_float_count: int
    violations: int
    open_delays: int
    level: Literal["danger", "warning", "ok"]


class AttentionOut(BaseModel):
    items: list[AttentionItem]
