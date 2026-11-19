"""조건 하나(Condition)와 언제나 들어가는 기본 규칙(BASE_RULES).

params 는 JSON 그대로의 모양이다(날짜는 ISO 글자, start_md·end_md 는 정수 두 개의 목록).
- finish_by {date} · start_after {date} · milestone_by {activity_id, date}
- resource_cap {resource_id, capacity} · calendar {days_per_week, holidays: "KR" | [ISO 날짜…]}
- blocked_period {start_md, end_md, tag} · min_gap {after_tag, days} · max_duration {days}
- text_only {} · duration_per_unit (모양이 정해지지 않았다. 자동 점검하지 않는다)
- 기본 규칙(no_cycle · no_dangling · calendar · valid, 겹 "base") {}

`checkable` 이 False 인 조건은 점검하지 않는다. 화면에는 "자동 점검 안 됨" 으로만 보인다.
"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, get_args

Layer = Literal["base", "domain", "mine", "input"]
Kind = Literal[
    "no_cycle", "no_dangling", "calendar", "valid", "finish_by", "start_after", "milestone_by",
    "resource_cap", "blocked_period", "min_gap", "duration_per_unit", "max_duration", "text_only",
]
# source: "기본 규칙" | "분야 규칙" | "내 규칙" | "프롬프트" | "질문지" | "문서"

# 코드로 점검하지 않는 종류. duration_per_unit 은 params 모양과 잣대가 아직 없다.
UNCHECKED_KINDS = frozenset({"text_only", "duration_per_unit"})


@dataclass(frozen=True)
class Condition:
    id: str
    layer: Layer
    kind: Kind
    params: dict
    text: str
    source: str
    enabled: bool = True
    overridden_by: str | None = None  # 조립에서 진 조건이면 이긴 조건의 id

    @property
    def checkable(self) -> bool:
        return self.kind not in UNCHECKED_KINDS

    def to_dict(self) -> dict:
        """저장 모양(JSON 그대로 쓸 수 있다). checkable 은 넣지 않는다(kind 로 정해진다)."""
        return {
            "id": self.id,
            "layer": self.layer,
            "kind": self.kind,
            "params": deepcopy(self.params),
            "text": self.text,
            "source": self.source,
            "enabled": self.enabled,
            "overridden_by": self.overridden_by,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Condition":
        """to_dict 의 반대. enabled·overridden_by 는 없어도 된다. 모르는 layer·kind 면 ValueError."""
        if d["layer"] not in get_args(Layer):
            raise ValueError(f"unknown condition layer: {d['layer']!r}")
        if d["kind"] not in get_args(Kind):
            raise ValueError(f"unknown condition kind: {d['kind']!r}")
        return cls(
            id=d["id"],
            layer=d["layer"],
            kind=d["kind"],
            params=deepcopy(d["params"]),
            text=d["text"],
            source=d["source"],
            enabled=d.get("enabled", True),
            overridden_by=d.get("overridden_by"),
        )


def _base(name: str, kind: Kind, text: str) -> Condition:
    return Condition(f"base.{name}", "base", kind, {}, text, "기본 규칙")


# 일정이 계산되면 지켜진 것이다. 계산이 ScheduleError 로 막히면 그 코드에 맞는 하나가 어겨진다.
BASE_RULES: tuple[Condition, ...] = (
    _base("no_cycle", "no_cycle", "선후 관계에 고리가 없음"),
    _base("no_dangling", "no_dangling", "관계가 있는 액티비티만 가리킴"),
    _base("calendar", "calendar", "달력에 일할 수 있는 날이 있음"),
    _base("valid", "valid", "기간과 ID가 올바름"),
)
BASE_IDS = frozenset(b.id for b in BASE_RULES)
