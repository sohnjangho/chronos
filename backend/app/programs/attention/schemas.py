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
    points_count: int | None = None  # 지금 버전의 관리 포인트 수(계산이 안 되는 일정은 None)
    points_changed: int = 0  # 마지막 바뀜의 새 포인트 + 여유가 준 포인트 수(열린 지연이 있으면 그 가정 기준)
    human_read_wait: int = 0  # 사진 사람 판독 대기 수(PM 11-24). 사람 판독을 할 수 있는 사람에게만 센다, 등급에는 넣지 않는다


class AttentionOut(BaseModel):
    items: list[AttentionItem]
