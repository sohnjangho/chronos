"""생성 루프의 코드 쪽: LLM 답 읽기, 일정(Schedule) 만들기, 착공일, 정밀도 맞춤 알림.

LLM 답의 날짜 칸(es·start·constraint …)은 모르는 칸이라 읽을 때 버린다.
자원·꼬리표는 분야 묶음의 작업 유형으로 코드가 붙인다.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.model import (
    Activity,
    CalendarSpec,
    Relation,
    RelType,
    Resource,
    Schedule,
    WbsNode,
)
from app.domains.loader import ActivityType, DomainPack, levels
from app.harness.assemble import holidays_of
from app.harness.conditions import Condition, condition_problem, validate_params
from app.llm.client import LlmReply

# LLM 이 내는 숫자의 한도(근무일). 넘으면 깨진 초안 — core 날짜 셈이 넘치거나 오래 걸리지 않게
MAX_OD = 3650
MAX_LAG = 365
MAX_ACTIVITIES = 400
NOT_JSON = "답이 JSON 객체가 아닙니다."
CUT_BY_LENGTH = "답이 길이 제한에 걸려 잘렸습니다. 액티비티를 묶어 더 짧게 다시 내 주세요."
START_LABEL = "착공일"
# 착공일로 읽는 사실(fact)의 label. 이 말과 똑같을 때만("외부 마감 시작" 같은 것은 아니다)
START_LABELS = frozenset({"착공", "착공일", "착수", "착수일", "시작일", "프로젝트 시작"})
ROUGH_RESOURCE_MESSAGE = "개략 일정(L1·L2)에서는 자원을 다루지 않습니다."
ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MAX_ERRORS = 3


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")  # 날짜 등 모르는 칸은 버린다


class WbsIn(_Loose):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    parent: str | None = None


class PredIn(_Loose):
    pred: str = Field(min_length=1)
    type: RelType = "FS"
    lag: int = Field(default=0, ge=-MAX_LAG, le=MAX_LAG)


class ActIn(_Loose):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["task", "start_ms", "finish_ms"]
    wbs: str
    od: int = Field(ge=0, le=MAX_OD)
    tags: list[str] = []
    predecessors: list[PredIn] = []


class WbsReply(_Loose):
    wbs: list[WbsIn] = Field(min_length=1)


class DraftReply(_Loose):
    wbs: list[WbsIn] | None = None  # 고침에서 WBS 를 바꿀 때만
    activities: list[ActIn] = Field(min_length=1, max_length=MAX_ACTIVITIES)


class DraftProblem(Exception):
    """초안이 깨졌다. message 는 LLM 에 돌려줄 글, activity_count 는 읽은 액티비티 수(못 읽었으면 0)."""

    def __init__(self, message: str, activity_count: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.activity_count = activity_count


def _reason(error: ValidationError) -> str:
    parts = []
    for item in error.errors(include_input=False, include_url=False)[:_MAX_ERRORS]:
        where = ".".join(str(p) for p in item["loc"]) or "답"
        parts.append(f"{where}: {item['msg']}")
    return "; ".join(parts)


def _read[M: BaseModel](reply: LlmReply, model: type[M]) -> M:
    if reply.finish_reason == "length":  # max_tokens 에 걸려 잘린 답은 모양이 맞아도 읽지 않는다
        raise DraftProblem(CUT_BY_LENGTH)
    if reply.parsed is None:
        raise DraftProblem(NOT_JSON)
    try:
        return model.model_validate(reply.parsed)
    except ValidationError as e:
        raise DraftProblem(f"답의 모양이 틀렸습니다: {_reason(e)}") from None


def wbs_problem(nodes: Sequence[WbsIn]) -> str | None:
    seen: set[str] = set()
    for node in nodes:
        if node.code in seen:
            return f"WBS code 가 겹칩니다: {node.code}"
        if node.parent is not None and node.parent not in seen:
            return f"WBS {node.code} 의 상위 {node.parent} 가 앞에 없습니다."
        seen.add(node.code)
    return None


def read_wbs(reply: LlmReply) -> list[WbsIn]:
    nodes = _read(reply, WbsReply).wbs
    if problem := wbs_problem(nodes):
        raise DraftProblem(problem)
    return nodes


def read_draft(reply: LlmReply, wbs: list[WbsIn]) -> tuple[DraftReply, list[WbsIn]]:
    """(초안, 쓸 WBS). 초안이 새 WBS 를 내면 그것을 쓴다. 깨졌으면 DraftProblem."""
    draft = _read(reply, DraftReply)
    count = len(draft.activities)
    nodes = draft.wbs if draft.wbs else wbs
    if problem := wbs_problem(nodes):
        raise DraftProblem(problem, count)
    codes = {n.code for n in nodes}
    missing = [f"{a.id} → {a.wbs}" for a in draft.activities if a.wbs not in codes]
    if missing:
        raise DraftProblem("없는 WBS 를 가리킵니다: " + ", ".join(missing), count)
    return draft, nodes


def wbs_depth(nodes: Sequence[WbsIn]) -> int:
    depth: dict[str, int] = {}
    for node in nodes:
        depth[node.code] = 1 if node.parent is None else depth[node.parent] + 1
    return max(depth.values(), default=0)


def _span(span: list[int]) -> str:
    return str(span[0]) if span[0] == span[1] else f"{span[0]}~{span[1]}"


def fit_warnings(level: str, nodes: Sequence[WbsIn], activity_count: int) -> list[str]:
    """정밀도 정의와 맞지 않는 WBS 깊이·액티비티 수. 위반이 아니다(알림)."""
    d = levels()[level]
    out = []
    depth = wbs_depth(nodes)
    if not d.wbs_depth[0] <= depth <= d.wbs_depth[1]:
        out.append(f"WBS 깊이가 {depth}단계입니다. {level}는 {_span(d.wbs_depth)}단계입니다.")
    count = d.activity_count
    if count is not None and not count[0] <= activity_count <= count[1]:
        out.append(f"액티비티가 {activity_count}개입니다. {level}는 {_span(count)}개입니다.")
    return out


def uses_resources(level: str) -> bool:
    """정밀도 정의에 주요 자원이 있는가(L1·L2 는 '없음' — 개략 일정)."""
    return levels()[level].resources == "주요 자원"


def _fact_date(fact: dict) -> date | None:
    """label 이 START_LABELS 가운데 하나인 사실의 값에 있는 날짜(YYYY-MM-DD, 조건 날짜 범위 안)."""
    if fact["label"].strip() not in START_LABELS:
        return None
    found = ISO_DAY.search(fact["value"])
    if found is None or validate_params("start_after", {"date": found.group()}) is not None:
        return None
    return date.fromisoformat(found.group())


def start_date(conditions: Sequence[Condition], facts: Sequence[dict], today: date) -> tuple[date, list[dict]]:
    """(사업 시작일, 더할 가정). 조립된 목록의 켜진 start_after 조건 → 알고 있는 착공일 → 오늘 다음 월요일(가정)."""
    for c in reversed(conditions):
        if c.kind == "start_after" and c.enabled and condition_problem(c) is None:
            return date.fromisoformat(c.params["date"]), []
    for fact in facts:
        if (day := _fact_date(fact)) is not None:
            return day, []
    monday = today + timedelta(days=7 - today.weekday())
    note = f"착공일을 알 수 없어 {monday.isoformat()}로 가정했습니다."
    return monday, [{"label": START_LABEL, "value": note, "source": "가정"}]


def condition_tags(conditions: Sequence[Condition]) -> list[str]:
    """켜져 있고 형식이 맞는 조건이 가리키는 꼬리표(금지 기간·간격)."""
    tags = []
    for c in conditions:
        if c.enabled and condition_problem(c) is None and c.kind in ("blocked_period", "min_gap"):
            tags.append(c.params["tag" if c.kind == "blocked_period" else "after_tag"])
    return tags


@dataclass(frozen=True)
class Setting:
    """초안을 일정으로 만들 때 코드가 정하는 것."""

    start: date
    calendar: CalendarSpec
    resources: tuple[Resource, ...]  # 정밀도에 자원이 없으면 비어 있다
    types: tuple[ActivityType, ...]
    known_tags: tuple[str, ...]  # 작업 유형 꼬리표 + 조건 꼬리표(차례 유지)


def setting(pack: DomainPack, level: str, start: date, extra_tags: Sequence[str]) -> Setting:
    cal = pack.default_calendar
    keys = pack.key_resources if uses_resources(level) else []
    resources = tuple(Resource(k.id, k.name, k.unit, 1) for k in keys)
    known = dict.fromkeys([*(t.tag for t in pack.activity_types), *extra_tags])
    return Setting(
        start=start,
        calendar=CalendarSpec(cal.days_per_week, holidays_of(cal.holidays)),
        resources=resources,
        types=tuple(pack.activity_types),
        known_tags=tuple(known),
    )


def _classify(a: ActIn, s: Setting) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(꼬리표, 자원). LLM 꼬리표는 아는 것만 두고, 이름에 작업 유형 낱말이 있으면 그 꼬리표를 더한다."""
    tags = [t for t in a.tags if t in s.known_tags]
    tags += [t.tag for t in s.types if any(word in a.name for word in t.name_keywords)]
    tags = list(dict.fromkeys(tags))
    if not s.resources:
        return tuple(tags), ()
    resources = dict.fromkeys(r for t in s.types if t.tag in tags for r in t.resources)
    return tuple(tags), tuple(resources)


def build(draft: DraftReply, nodes: Sequence[WbsIn], s: Setting) -> Schedule:
    """초안 → 일정. 날짜는 넣지 않는다(시작일·달력만, 계산은 core 가 한다)."""
    activities = []
    relations = []
    for a in draft.activities:
        tags, resources = _classify(a, s)
        activities.append(Activity(a.id, a.name, a.kind, a.wbs, a.od, resources=resources, tags=tags))
        relations += [Relation(p.pred, a.id, p.type, p.lag) for p in a.predecessors]
    return Schedule(
        start=s.start,
        calendar=s.calendar,
        wbs=tuple(WbsNode(n.code, n.name, n.parent) for n in nodes),
        activities=tuple(activities),
        relations=tuple(relations),
        resources=s.resources,
    )
