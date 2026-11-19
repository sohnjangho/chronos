"""조건 하나(Condition)와 언제나 들어가는 기본 규칙(BASE_RULES), 그리고 조건 형식 검사.

params 는 JSON 그대로의 모양이다(날짜는 ISO 글자, start_md·end_md 는 정수 두 개의 목록).
- finish_by {date} · start_after {date} · milestone_by {activity_id, date}
- resource_cap {resource_id, capacity} · calendar {days_per_week, holidays: "KR" | [ISO 날짜…]}
- blocked_period {start_md, end_md, tag} · min_gap {after_tag, days, unit?: "workdays" | "calendar_days"}
- max_duration {days} · text_only {} · duration_per_unit (모양이 정해지지 않았다. 자동 점검하지 않는다)
- 기본 규칙(no_cycle · no_dangling · calendar · valid, 겹 "base") {}

`checkable` 이 False 인 조건은 점검하지 않는다. 화면에는 "자동 점검 안 됨" 으로만 보인다.
형식이 틀린 조건(`condition_problem` 이 글을 돌려주는 것)은 겨루지도, 일정에 넣지도, 점검하지도 않는다.
"""

from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Literal, get_args

Layer = Literal["base", "domain", "mine", "input"]
Kind = Literal[
    "no_cycle", "no_dangling", "calendar", "valid", "finish_by", "start_after", "milestone_by",
    "resource_cap", "blocked_period", "min_gap", "duration_per_unit", "max_duration", "text_only",
]
# source: "기본 규칙" | "분야 규칙" | "내 규칙" | "프롬프트" | "질문지" | "문서"
_LAYERS = frozenset(get_args(Layer))
_KINDS = frozenset(get_args(Kind))

# 코드로 점검하지 않는 종류. duration_per_unit 은 params 모양과 잣대가 아직 없다.
UNCHECKED_KINDS = frozenset({"text_only", "duration_per_unit"})


class ConditionFormatError(ValueError):
    """저장된 조건 dict 를 읽을 수 없다. condition_id 는 id 가 없으면 "?"."""

    def __init__(self, condition_id: str, message: str) -> None:
        super().__init__(f"{condition_id}: {message}")
        self.condition_id = condition_id
        self.message = message


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
        """저장 모양(JSON 그대로 쓸 수 있다). checkable 은 읽기 전용이다(from_dict 가 무시한다)."""
        return {
            "id": self.id,
            "layer": self.layer,
            "kind": self.kind,
            "params": deepcopy(self.params),
            "text": self.text,
            "source": self.source,
            "enabled": self.enabled,
            "overridden_by": self.overridden_by,
            "checkable": self.checkable,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Condition":
        """to_dict 의 반대. enabled·overridden_by 는 없어도 된다. 틀리면 ConditionFormatError."""
        if not isinstance(d, dict):
            raise ConditionFormatError("?", "조건이 객체가 아닙니다.")
        cid = d.get("id")
        if not (isinstance(cid, str) and cid):
            raise ConditionFormatError("?", "'id' 칸이 없습니다.")
        problem = _dict_problem(d)
        if problem is None:
            c = cls(
                id=cid,
                layer=d["layer"],
                kind=d["kind"],
                params=deepcopy(d["params"]),
                text=d["text"],
                source=d["source"],
                enabled=d.get("enabled", True),
                overridden_by=d.get("overridden_by"),
            )
            problem = condition_problem(c)
        if problem is not None:
            raise ConditionFormatError(cid, problem)
        return c


def _bad(key: str, what: str) -> str:
    return f"'{key}' 칸 값이 올바르지 않습니다: {what}"


# 저장된 dict 의 칸: (이름, 형, 설명). params 의 모양은 validate_params 가 본다.
_DICT_FIELDS = (("kind", str, "글자"), ("layer", str, "글자"), ("params", dict, "객체"),
                ("text", str, "글자"), ("source", str, "글자"))


def _dict_problem(d: dict) -> str | None:
    for key, typ, what in _DICT_FIELDS:
        if key not in d:
            return f"'{key}' 칸이 없습니다."
        if not isinstance(d[key], typ):
            return _bad(key, what)
    if not isinstance(d.get("enabled", True), bool):
        return _bad("enabled", "참/거짓")
    if not isinstance(d.get("overridden_by"), str | None):
        return _bad("overridden_by", "글자")
    return None


# ── params 검사 ─────────────────────────────────────────────────────


def _is_date(v: object) -> bool:
    if not isinstance(v, str):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _is_count(v: object) -> bool:
    return type(v) is int and v >= 0


def _is_name(v: object) -> bool:
    return isinstance(v, str) and v != ""


def _is_month_day(v: object) -> bool:
    """[월, 일]. 2월 29일도 된다(윤년 기준)."""
    if not (isinstance(v, list | tuple) and len(v) == 2 and all(type(x) is int for x in v)):
        return False
    try:
        date(2028, v[0], v[1])
    except ValueError:
        return False
    return True


def _is_holidays(v: object) -> bool:
    return v == "KR" or (isinstance(v, list) and all(_is_date(x) for x in v))


_Check = tuple[Callable[[object], bool], str]
_DATE: _Check = (_is_date, "날짜(YYYY-MM-DD)")
_NAME: _Check = (_is_name, "빈칸이 아닌 글자")
_COUNT: _Check = (_is_count, "0 이상의 정수")
_MONTH_DAY: _Check = (_is_month_day, "[월, 일]")
_DAYS_PER_WEEK: _Check = (lambda v: type(v) is int and v in (5, 6, 7), "5·6·7 가운데 하나")
_HOLIDAYS: _Check = (_is_holidays, '"KR" 또는 날짜(YYYY-MM-DD) 목록')
_UNIT: _Check = (lambda v: v in ("workdays", "calendar_days"), '"workdays" 또는 "calendar_days"')

# kind → (칸, 검사, 꼭 있어야 하는가). 여기 없는 종류는 params 가 객체이기만 하면 된다.
_PARAMS: dict[str, tuple[tuple[str, _Check, bool], ...]] = {
    "finish_by": (("date", _DATE, True),),
    "start_after": (("date", _DATE, True),),
    "milestone_by": (("activity_id", _NAME, True), ("date", _DATE, True)),
    "resource_cap": (("resource_id", _NAME, True), ("capacity", _COUNT, True)),
    "calendar": (("days_per_week", _DAYS_PER_WEEK, True), ("holidays", _HOLIDAYS, True)),
    "blocked_period": (("start_md", _MONTH_DAY, True), ("end_md", _MONTH_DAY, True), ("tag", _NAME, True)),
    "min_gap": (("after_tag", _NAME, True), ("days", _COUNT, True), ("unit", _UNIT, False)),
    "max_duration": (("days", _COUNT, True),),
}


def validate_params(kind: str, params: object) -> str | None:
    """kind 에 맞는 params 인지. 틀리면 무엇이 틀렸는지 한국어 글, 맞으면 None. 모르는 칸은 상관하지 않는다."""
    if kind not in _KINDS:
        return f"알 수 없는 조건 종류입니다: {kind}"
    if not isinstance(params, dict):
        return _bad("params", "객체")
    for key, (ok, what), required in _PARAMS.get(kind, ()):
        if key not in params:
            if required:
                return f"'{key}' 칸이 없습니다."
        elif not ok(params[key]):
            return _bad(key, what)
    return None


def condition_problem(c: Condition) -> str | None:
    """조건이 형식에 맞지 않으면 그 까닭(한국어), 맞으면 None.

    기본 규칙 id 인 조건은 params 를 보지 않는다. 겹이 "base" 인데 기본 규칙 id 가 아니면 틀린 것이다.
    """
    if c.layer not in _LAYERS:
        return f"알 수 없는 겹입니다: {c.layer}"
    if c.kind not in _KINDS:
        return f"알 수 없는 조건 종류입니다: {c.kind}"
    if c.id in BASE_IDS:
        return None
    if c.layer == "base":
        return "기본 규칙은 바꿀 수 없습니다."
    return validate_params(c.kind, c.params)


def read_conditions(stored: Sequence[object]) -> tuple[list[Condition], list[dict]]:
    """저장된 조건 목록 → (읽은 조건, 읽지 못한 것 [{condition_id, message}]). 순서는 그대로."""
    good: list[Condition] = []
    bad: list[dict] = []
    for d in stored:
        try:
            good.append(Condition.from_dict(d))
        except ConditionFormatError as e:
            bad.append({"condition_id": e.condition_id, "message": e.message})
    return good, bad


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
