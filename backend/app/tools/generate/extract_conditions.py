"""generate.extract_conditions — 요청·질문지 답·가정에서 입력 조건과 사실을 뽑는다(LLM light 한 번).

LLM 이 낸 조건은 하네스 형식 검사(condition_problem)를 거친다. 틀린 것은 버리고 dropped 에 까닭을 남긴다.
조건 id 는 `in.<kind>` 또는 `in.<kind>.<대상>`(resource_cap 은 자원 id, blocked_period 는 꼬리표).
같은 id 가 다시 나오면 `.2`, `.3` … 을 붙인다.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

import app.tools.generate as package
from app.agent.generation_steps import compact, level_line, strict_object, system_prompt
from app.domains.loader import DomainPack, UnknownDomain, load
from app.harness.conditions import Condition, validate_params
from app.llm.client import LlmFailed, LlmNotReady
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool

ALLOWED_KINDS = ("start_after", "finish_by", "calendar", "blocked_period", "resource_cap", "max_duration", "text_only")
SOURCES = ("프롬프트", "질문지", "가정")
UNREADABLE_MESSAGE = "조건을 읽지 못했습니다. 다시 시도해 주세요."
# 종류마다 params 로 옮길 칸(LLM 답의 칸 이름 그대로)
_PARAM_FIELDS = {
    "start_after": ("date",),
    "finish_by": ("date",),
    "calendar": ("days_per_week", "holidays"),
    "blocked_period": ("start_md", "end_md", "tag"),
    "resource_cap": ("resource_id", "capacity"),
    "max_duration": ("days",),
    "text_only": (),
}
_TARGET = {"resource_cap": "resource_id", "blocked_period": "tag"}

_STR = {"type": "string"}
_NULL_STR = {"type": ["string", "null"]}
_NULL_INT = {"type": ["integer", "null"]}
_NULL_PAIR = {"type": ["array", "null"], "items": {"type": "integer"}}
_CONDITION = strict_object({
    "kind": {"type": "string", "enum": list(ALLOWED_KINDS)},
    "text": _STR,
    "source": {"type": "string", "enum": list(SOURCES)},
    "date": _NULL_STR,
    "resource_id": _NULL_STR,
    "capacity": _NULL_INT,
    "days_per_week": _NULL_INT,
    "holidays": {"type": ["array", "null"], "items": _STR},
    "start_md": _NULL_PAIR,
    "end_md": _NULL_PAIR,
    "tag": _NULL_STR,
    "days": _NULL_INT,
})
EXTRACT_SCHEMA = strict_object({
    "conditions": {"type": "array", "items": _CONDITION},
    "facts": {"type": "array", "items": strict_object(
        {"label": _STR, "value": _STR, "source": {"type": "string", "enum": ["프롬프트", "질문지"]}}
    )},
    "assumptions": {"type": "array", "items": strict_object({"label": _STR, "value": _STR})},
    "unknown": {"type": "array", "items": _STR},
})


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str


class AssumedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    assumption: str


class ExtractIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="사용자의 요청(프롬프트)")
    domain: str = Field(description="분야 id(예: construction)")
    level: Literal["L1", "L2", "L3", "L4", "L5"] = Field(description="정밀도")
    answers: list[AnswerIn] = Field(default_factory=list, description="질문지·카드에서 받은 답")
    assumed: list[AssumedIn] = Field(default_factory=list, description="답하지 않아 가정으로 넘긴 질문")


class FactOut(BaseModel):
    label: str
    value: str
    source: str


class DroppedOut(BaseModel):
    kind: str
    reason: str


class ExtractOut(BaseModel):
    conditions: list[dict]  # Condition.to_dict() 모양, 겹 input
    facts: list[FactOut]
    assumptions: list[FactOut]  # source 는 "가정"
    unknown: list[str]
    dropped: list[DroppedOut]


class _Proposed(BaseModel):
    """LLM 이 낸 조건 한 줄(모르는 종류도 받아서 dropped 로 알린다)."""

    kind: str
    text: str = ""
    source: Literal["프롬프트", "질문지", "가정"] = "프롬프트"
    date: str | None = None
    resource_id: str | None = None
    capacity: int | None = None
    days_per_week: int | None = None
    holidays: list[str] | None = None
    start_md: list[int] | None = None
    end_md: list[int] | None = None
    tag: str | None = None
    days: int | None = None


class _Labeled(BaseModel):
    label: str
    value: str


class _Reply(BaseModel):
    conditions: list[_Proposed] = []
    facts: list[FactOut] = []
    assumptions: list[_Labeled] = []
    unknown: list[str] = []


def _params(p: _Proposed, pack: DomainPack) -> dict:
    """그 종류의 칸만 옮긴다. null 칸은 빼고(검사가 '칸이 없습니다' 로 알린다), 달력 공휴일은 분야 기본값."""
    params = {f: getattr(p, f) for f in _PARAM_FIELDS[p.kind] if getattr(p, f) is not None}
    if p.kind == "calendar":
        holidays = p.holidays if p.holidays is not None else pack.default_calendar.holidays
        params["holidays"] = "KR" if holidays == ["KR"] else holidays
    return params


def _problem(p: _Proposed, pack: DomainPack) -> str | None:
    if p.kind not in ALLOWED_KINDS:
        return f"쓸 수 없는 조건 종류입니다: {p.kind}"
    if p.kind == "resource_cap" and p.resource_id not in {k.id for k in pack.key_resources}:
        return f"없는 자원입니다: {p.resource_id}"
    return None


def _condition_id(kind: str, params: dict, used: set[str]) -> str:
    base = f"in.{kind}" + (f".{params[_TARGET[kind]]}" if kind in _TARGET else "")
    cid, n = base, 1
    while cid in used:
        n += 1
        cid = f"{base}.{n}"
    used.add(cid)
    return cid


def conditions_from(proposed: list[_Proposed], pack: DomainPack) -> tuple[list[dict], list[DroppedOut]]:
    kept: list[dict] = []
    dropped: list[DroppedOut] = []
    used: set[str] = set()
    for p in proposed:
        problem = _problem(p, pack)
        params = _params(p, pack) if problem is None else {}
        problem = problem or validate_params(p.kind, params)
        if problem is not None:
            dropped.append(DroppedOut(kind=p.kind, reason=problem))
            continue
        cid = _condition_id(p.kind, params, used)
        kept.append(Condition(cid, "input", p.kind, params, p.text.strip(), p.source).to_dict())
    return kept, dropped


def _user_text(args: ExtractIn, pack: DomainPack) -> str:
    lines = [level_line(args.level), f"요청(프롬프트): {args.text}", "질문지 답:"]
    lines += [f"- {a.question} → {a.answer}" for a in args.answers] or ["(없음)"]
    lines.append("답하지 않아 가정으로 넘긴 질문:")
    lines += [f"- {a.question} → 가정: {a.assumption}" for a in args.assumed] or ["(없음)"]
    lines.append("분야 주요 자원 id: " + compact([k.id for k in pack.key_resources]))
    return "\n".join(lines)


async def _ask(args: ExtractIn, pack: DomainPack, ctx: ToolContext) -> _Reply:
    messages = [
        {"role": "system", "content": system_prompt("extract", pack)},
        {"role": "user", "content": _user_text(args, pack)},
    ]
    llm = package.client_for(ctx)
    chat_session_id = getattr(ctx, "chat_session_id", None)  # 문맥이 대화 id 를 가질 때만
    try:
        reply = await llm.chat("light", messages, json_schema=EXTRACT_SCHEMA, chat_session_id=chat_session_id)
    except LlmNotReady as e:
        raise ToolError(e.message) from None
    except LlmFailed as e:
        raise ToolError(e.error.message) from None
    try:
        return _Reply.model_validate(reply.parsed)
    except ValidationError:
        raise ToolError(UNREADABLE_MESSAGE) from None


@tool(
    "generate.extract_conditions",
    "일정 요청·질문지 답·가정으로 넘긴 질문에서 입력 조건(준공 기한·착공·달력·금지 기간·자원 대수·최대 기간·글 조건)과 "
    "사실(facts)·가정(assumptions)을 뽑는다. 형식이 틀린 조건은 버리고 dropped 에 까닭을 남긴다. "
    "unknown 은 고른 정밀도에 꼭 있어야 하는데 아직 모르는 것 — 물을지(두 번째 질문) 가정할지 정할 때 쓴다. "
    "결과를 그대로 generate.run 에 넘긴다.",
)
async def extract_conditions(args: ExtractIn, ctx: ToolContext) -> ExtractOut:
    try:
        pack = load(args.domain)
    except UnknownDomain:
        raise ToolError(f"없는 분야입니다: {args.domain}") from None
    reply = await _ask(args, pack, ctx)
    conditions, dropped = conditions_from(reply.conditions, pack)
    return ExtractOut(
        conditions=conditions,
        facts=reply.facts,
        assumptions=[FactOut(label=a.label, value=a.value, source="가정") for a in reply.assumptions],
        unknown=reply.unknown,
        dropped=dropped,
    )
