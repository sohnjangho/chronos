"""일정 모델. 전부 바뀌지 않는(frozen) 자료 구조다."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

RelType = Literal["FS", "SS", "FF", "SF"]


@dataclass(frozen=True)
class Constraint:
    """SNET: 이 날 이후 시작 / FNLT: 늦어도 이 날 종료."""

    type: Literal["SNET", "FNLT"]
    date: date


@dataclass(frozen=True)
class Activity:
    id: str
    name: str
    kind: Literal["task", "start_ms", "finish_ms"]
    wbs: str
    od: int
    rd: int | None = None
    progress: float = 0.0
    actual_start: date | None = None
    actual_finish: date | None = None
    constraint: Constraint | None = None
    resources: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Relation:
    pred: str
    succ: str
    type: RelType = "FS"
    lag: int = 0


@dataclass(frozen=True)
class WbsNode:
    code: str
    name: str
    parent: str | None


@dataclass(frozen=True)
class Resource:
    id: str
    name: str
    unit: str
    capacity: int


@dataclass(frozen=True)
class BlockedPeriod:
    """해마다 되풀이되는 작업 금지 기간. 예: (12,1)~(2,28), "타설"."""

    start_md: tuple[int, int]
    end_md: tuple[int, int]
    tag: str


@dataclass(frozen=True)
class CalendarSpec:
    days_per_week: Literal[5, 6, 7]
    holidays: tuple[date, ...] = ()
    blocked: tuple[BlockedPeriod, ...] = ()


@dataclass(frozen=True)
class Schedule:
    start: date
    calendar: CalendarSpec
    wbs: tuple[WbsNode, ...]
    activities: tuple[Activity, ...]
    relations: tuple[Relation, ...]
    resources: tuple[Resource, ...] = ()
    data_date: date | None = None
