"""정밀도 정의(levels.yaml)와 분야 묶음(<분야>/pack.yaml)을 읽고, 에이전트 지시문에 넣을 글을 만든다.

내용은 YAML 에만 둔다. 읽을 때 pydantic 으로 검사하고(모르는 칸은 거절) 프로세스마다 한 번만 읽는다.
돌려주는 것은 늘 깊은 사본이라 고쳐도 다음 호출에 영향이 없다.
분야 규칙은 app.harness.conditions.Condition 으로 읽혀야 하고 겹 "domain"·출처 "분야 규칙" 이어야 한다.
"""

from collections import Counter
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.harness.conditions import Condition

ROOT = Path(__file__).parent
LEVEL_IDS = ("L1", "L2", "L3", "L4", "L5")
# 분야 묶음의 규칙 한 줄에 쓸 수 있는 칸. overridden_by·checkable 은 조립·계산이 정하는 값이라 받지 않는다.
_RULE_KEYS = frozenset({"id", "layer", "kind", "params", "text", "source", "enabled"})
# 아는 조건 종류의 params 칸(app/harness/conditions 의 검사와 같은 칸 — 시험이 맞는지 본다).
# 하네스는 모르는 칸을 상관하지 않지만 분야 묶음은 오타(unti 등)를 막으려고 거절한다. 여기 없는 종류는 칸을 보지 않는다.
PARAM_KEYS: dict[str, frozenset[str]] = {
    "finish_by": frozenset({"date"}),
    "start_after": frozenset({"date"}),
    "milestone_by": frozenset({"activity_id", "date"}),
    "resource_cap": frozenset({"resource_id", "capacity"}),
    "calendar": frozenset({"days_per_week", "holidays"}),
    "blocked_period": frozenset({"start_md", "end_md", "tag"}),
    "min_gap": frozenset({"after_tag", "days", "unit"}),
    "max_duration": frozenset({"days"}),
    "text_only": frozenset(),
}


class UnknownDomain(LookupError):
    """분야 묶음이 없는 분야 id."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _ordered(span: list[int]) -> list[int]:
    if span[0] > span[1]:
        raise ValueError("[최소, 최대] 차례여야 합니다.")
    return span


Span = Annotated[list[Annotated[int, Field(ge=1)]], Field(min_length=2, max_length=2), AfterValidator(_ordered)]
Text = Annotated[str, Field(min_length=1)]


# ── 정밀도 5단계 ────────────────────────────────────────────────────


class LevelDef(_Strict):
    id: Literal["L1", "L2", "L3", "L4", "L5"]
    name: Text
    use: Text  # 쓰는 곳
    wbs_depth: Span
    activity_count: Span | None  # None = 고른 구간만(L5)
    time_unit: Literal["월", "주", "일", "일·교대"]
    resources: Literal["없음", "주요 자원"]
    must_contain: Text  # 일정에 꼭 있어야 하는 것


@cache
def _levels() -> dict[str, LevelDef]:
    data = yaml.safe_load((ROOT / "levels.yaml").read_text(encoding="utf-8"))
    defs = TypeAdapter(list[LevelDef]).validate_python(data)
    ids = tuple(d.id for d in defs)
    if ids != LEVEL_IDS:
        raise ValueError(f"levels.yaml 의 단계는 {LEVEL_IDS} 차례로 하나씩이어야 합니다: {ids}")
    return {d.id: d for d in defs}


def levels() -> dict[str, LevelDef]:
    """L1~L5 차례의 정의(깊은 사본)."""
    return {key: d.model_copy(deep=True) for key, d in _levels().items()}


def _span(span: list[int]) -> str:
    return str(span[0]) if span[0] == span[1] else f"{span[0]}~{span[1]}"


def levels_prompt() -> str:
    """에이전트 지시문용: 다섯 단계를 한 줄씩."""
    lines = ["정밀도 5단계:"]
    for d in levels().values():
        count = f"{_span(d.activity_count)}개" if d.activity_count else "고른 구간만"
        lines.append(
            f"- {d.id} {d.name} — 쓰는 곳: {d.use} · WBS 깊이: {_span(d.wbs_depth)} · 액티비티 수: {count}"
            f" · 기간 단위: {d.time_unit} · 자원: {d.resources} · 꼭 있어야 하는 것: {d.must_contain}"
        )
    return "\n".join(lines)


# ── 분야 묶음 ───────────────────────────────────────────────────────


class DefaultCalendar(_Strict):
    days_per_week: Annotated[int, Field(ge=5, le=7)]
    holidays: Literal["KR"] | list[str]  # "KR" = 한국 법정 공휴일, 또는 ISO 날짜 목록


class KeyResource(_Strict):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    name: Text
    unit: Text  # 대·명·조 …
    tags: list[Text]  # 이 자원을 쓰는 작업 유형


class ActivityType(_Strict):
    tag: Text
    name_keywords: Annotated[list[Text], Field(min_length=1)]  # 액티비티 이름에 이 말이 있으면 이 유형
    resources: list[str] = []  # key_resources 의 id


class WbsNode(_Strict):
    code: Text
    name: Text
    parent: str | None = None  # 위 단계의 code(앞에 나와야 한다)


class AssumptionDefault(_Strict):
    key: Text
    label: Text
    value: Text
    note: str = ""


def _rule(raw: dict) -> dict:
    """규칙 한 줄을 검사하고 Condition.to_dict 모양에서 _RULE_KEYS 칸만 남긴다(다시 읽어도 된다)."""
    extra = sorted(set(raw) - _RULE_KEYS)
    if extra:
        raise ValueError(f"규칙 {raw.get('id')!r} 에 모르는 칸이 있습니다: {extra}")
    try:
        c = Condition.from_dict(raw)
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"규칙 {raw.get('id')!r} 을 조건으로 읽을 수 없습니다: {e}") from None
    if (c.layer, c.source) != ("domain", "분야 규칙"):
        raise ValueError(f"규칙 {c.id!r} 은 겹 'domain', 출처 '분야 규칙' 이어야 합니다.")
    unknown = sorted(set(c.params) - PARAM_KEYS.get(c.kind, set(c.params)))
    if unknown:
        raise ValueError(f"규칙 {c.id!r} 의 params 에 모르는 칸이 있습니다: {unknown}")
    return {key: value for key, value in c.to_dict().items() if key in _RULE_KEYS}


def _duplicates(values: list[str]) -> list[str]:
    return [v for v, n in Counter(values).items() if n > 1]


def _rule_line(raw: dict) -> str:
    """규칙 한 줄. 자동 점검하는 규칙은 어떻게 점검하는지(kind 와 params)도 보인다."""
    c = Condition.from_dict(raw)
    if not c.checkable:
        return f"- {c.text} [{c.id} · 자동 점검 안 됨]"
    params = ", ".join(f"{key}={value}" for key, value in c.params.items())
    return f"- {c.text} [{c.id} · 자동 점검: {c.kind} {params}]"


class DomainPack(_Strict):
    id: Text
    name: Text
    terms: dict[str, str]  # 영어 열쇠 → 이 분야에서 쓰는 말
    default_calendar: DefaultCalendar
    rules_raw: list[dict] = Field(alias="rules")  # Condition.to_dict 모양에서 overridden_by·checkable 을 뺀 것
    key_resources: list[KeyResource]
    activity_types: list[ActivityType]
    wbs_template: list[WbsNode]
    assumption_defaults: list[AssumptionDefault]

    @field_validator("rules_raw")
    @classmethod
    def _rules(cls, value: list[dict]) -> list[dict]:
        rules = [_rule(r) for r in value]
        if dup := _duplicates([r["id"] for r in rules]):
            raise ValueError(f"규칙 id 가 겹칩니다: {dup}")
        return rules

    @model_validator(mode="after")
    def _references(self) -> "DomainPack":
        if dup := _duplicates([k.id for k in self.key_resources]):
            raise ValueError(f"자원 id 가 겹칩니다: {dup}")
        if dup := _duplicates([t.tag for t in self.activity_types]):
            raise ValueError(f"작업 유형이 겹칩니다: {dup}")
        # 자원의 tags 와 작업 유형의 resources 는 같은 연결을 양쪽에서 적은 것이다.
        by_resource = {(t, k.id) for k in self.key_resources for t in k.tags}
        by_type = {(t.tag, r) for t in self.activity_types for r in t.resources}
        if by_resource != by_type:
            raise ValueError(f"자원과 작업 유형의 연결이 맞지 않습니다: {sorted(by_resource ^ by_type)}")
        seen: set[str] = set()
        for node in self.wbs_template:
            if node.code in seen:
                raise ValueError(f"WBS code 가 겹칩니다: {node.code}")
            if node.parent is not None and node.parent not in seen:
                raise ValueError(f"WBS {node.code} 의 parent {node.parent} 가 앞에 없습니다.")
            seen.add(node.code)
        return self

    def prompt(self) -> str:
        """에이전트 지시문용: 용어·달력·규칙·주요 자원·작업 유형·WBS 틀·가정 기준값."""
        return "\n".join(
            [f"분야: {self.name} ({self.id})", *self._basics(), *self._rules_and_resources(), *self._wbs(), *self._defaults()]
        )

    def _basics(self) -> list[str]:
        cal = self.default_calendar
        holidays = cal.holidays if isinstance(cal.holidays, str) else ", ".join(cal.holidays)
        return [
            "용어: " + ", ".join(f"{word}({key})" for key, word in self.terms.items()),
            f"기본 달력: 주 {cal.days_per_week}일, 공휴일 {holidays}",
        ]

    def _rules_and_resources(self) -> list[str]:
        names = {k.id: k.name for k in self.key_resources}
        lines = ["분야 규칙:"]
        lines += [_rule_line(raw) for raw in self.rules_raw]
        lines.append("주요 자원 후보:")
        lines += [f"- {k.name}({k.id}, 단위 {k.unit}) — 쓰는 작업: {', '.join(k.tags)}" for k in self.key_resources]
        lines.append("작업 유형(액티비티 이름에 이 말이 있으면 그 유형):")
        for t in self.activity_types:
            resources = ", ".join(names[r] for r in t.resources) or "없음"
            lines.append(f"- {t.tag}: {', '.join(t.name_keywords)} → 자원 {resources}")
        return lines

    def _wbs(self) -> list[str]:
        depth: dict[str, int] = {}
        lines = ["대표 WBS 틀:"]
        for node in self.wbs_template:
            depth[node.code] = 0 if node.parent is None else depth[node.parent] + 1
            lines.append(f"{'  ' * depth[node.code]}- {node.code} {node.name}")
        return lines

    def _defaults(self) -> list[str]:
        lines = ["가정할 때 쓰는 기준값:"]
        for a in self.assumption_defaults:
            lines.append(f"- {a.label}: {a.value}" + (f" ({a.note})" if a.note else ""))
        return lines


def read_pack(path: Path) -> DomainPack:
    """파일 하나를 읽어 검사한다(캐시하지 않음). 틀리면 pydantic ValidationError."""
    return DomainPack.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def domains() -> list[str]:
    """분야 묶음이 있는 분야 id(이름 순)."""
    return sorted(p.parent.name for p in ROOT.glob("*/pack.yaml"))


@cache
def _load(domain_id: str) -> DomainPack:
    pack = read_pack(ROOT / domain_id / "pack.yaml")
    if pack.id != domain_id:
        raise ValueError(f"{domain_id}/pack.yaml 의 id 가 {pack.id!r} 입니다.")
    return pack


def load(domain_id: str) -> DomainPack:
    """분야 묶음(깊은 사본). 없는 분야면 UnknownDomain. 파일은 프로세스마다 한 번만 읽는다."""
    if domain_id not in domains():
        raise UnknownDomain(domain_id)
    return _load(domain_id).model_copy(deep=True)
