"""도구 묶음의 등급표와 도구 정의(Task 67). 음성 에이전트와 글 에이전트가 **같은** 도구를 받고, 어느 도구를 받는지는 번호로
정한 발신자 등급(Caller.caller_class)과 매체만으로 코드가 정한다. 도구를 돌리는 것은 tools.Toolbox 다.

- for_class(등급, 매체) — 그 세션에 줄 도구 이름. 등급표 밖의 등급·매체는 ValueError(열린 묶음으로 넘어가지 않는다).
  blocked·outside_test 는 세션이 만들어지지 않으므로 빈 묶음이다.
- ARGS — 도구마다의 인자 꼴(pydantic, extra="forbid"). **일정·연락처·협력사 id 칸은 어디에도 없다** — 범위는 Scope 에서만
  오고, 현장은 이름(site)으로만 받아 그 상대의 후보 안에서 코드가 맞춘다. 주지 않아도 되는 글 칸은 빈 글이 기본값이다
  (음성 모델의 도구 정의가 null·anyOf 를 못 읽는 경우가 있어 꼴을 단순하게 둔다).
- tool_defs(이름들) — 세션에 그대로 넘길 ToolDef(이름·설명·JSON Schema). 설명에는 번호·등급 이름이 없다.
"""

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.outreach.harness.types import (
    SHARED_TOOLS,
    VOICE_ONLY_TOOLS,
    CallerClass,
    Medium,
    ToolDef,
)

SHARED = SHARED_TOOLS  # 음성·글 공통 10개(이름표 차례)
VOICE_ONLY = VOICE_ONLY_TOOLS  # 통화에만: end_call · confirm_person
ALL = SHARED + VOICE_ONLY

_MEMO = frozenset({"take_message", "propose_contact", "handoff_to_human"})  # 모르는 번호: 메모·새 연락처·긴급 알림
_BY_CLASS: Mapping[str, frozenset[str]] = MappingProxyType({
    "outbound": frozenset(SHARED),  # 도구는 다 받지만 사실 범위는 그 협력사·공종까지(Scope.facts "trade" — 관리자 등급 연락처만 "all")
    "contact": frozenset(SHARED), "contact_multi": frozenset(SHARED), "shared": frozenset(SHARED),
    "internal": frozenset({"find_contact", "schedule_fact", "take_message", "handoff_to_human"}),
    "do_not_contact": frozenset({"take_message"}),
    "unknown": _MEMO, "withheld": _MEMO,
    "blocked": frozenset(), "outside_test": frozenset(),  # 받지 않는다 — 세션이 없다
})
_VOICE_BY_CLASS: Mapping[str, frozenset[str]] = MappingProxyType({
    **{cls: frozenset({"end_call"}) for cls in _BY_CLASS},
    "outbound": frozenset(VOICE_ONLY),  # confirm_person 은 거는 통화의 첫 확인
    "blocked": frozenset(), "outside_test": frozenset(),
})


def for_class(caller_class: CallerClass, medium: Medium) -> frozenset[str]:
    """그 등급·그 매체의 세션이 받는 도구 이름."""
    if caller_class not in get_args(CallerClass) or medium not in get_args(Medium):
        raise ValueError("등급표에 없는 등급이거나 매체가 sms·call 이 아닙니다")
    shared = _BY_CLASS[caller_class]
    return shared | _VOICE_BY_CLASS[caller_class] if medium == "call" else shared


# ── 인자 꼴 ──────────────────────────────────────────────────────────

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
MaybeName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Words = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
MaybeWords = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
SITE = "어느 현장 일인지 상대가 말한 현장 이름. 상대가 말하지 않았으면 비워 둔다."


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindContact(_Args):
    query: Name = Field(description="찾을 사람의 이름이나 담당")
    site: MaybeName = Field("", description=SITE)
    redirect: bool = Field(False, description="상대가 「담당은 그 사람」이라고 알려 주었을 때만 참")


class ProposeContact(_Args):
    name: Name = Field(description="새로 알게 된 사람의 이름")
    role_title: MaybeName = Field("", description="그 사람의 담당")
    phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] = Field(
        description="상대가 불러 준 전화번호")


class ScheduleFact(_Args):
    activity: Name = Field(description="상대가 물은 작업의 이름")
    site: MaybeName = Field("", description=SITE)


class MyRequests(_Args):
    site: MaybeName = Field("", description=SITE)


class RecordAnswer(_Args):
    question: Words = Field(description="우리가 물은 것")
    answer: Words = Field(description="상대의 답을 간추린 것")
    quote: Words = Field(description="그 답의 근거가 된 상대의 말 그대로")


class TakeMessage(_Args):
    text: Words = Field(description="담당자에게 전할 말")
    claimed_name: MaybeName = Field("", description="상대가 자기가 누구라고 밝혔으면 그 이름")


class ReportFromContact(_Args):
    kind: Literal["delay", "problem", "change_request", "other"] = Field(description="지연 · 문제 · 일정 변경 요청 · 그 밖")
    text: Words = Field(description="상대가 알린 내용")
    quote: Words = Field(description="근거가 된 상대의 말 그대로")
    site: MaybeName = Field("", description=SITE)


class ScheduleCallback(_Args):
    day_offset: int = Field(ge=0, le=14, description="오늘부터 며칠 뒤인가(오늘이면 0)")
    hour: int = Field(ge=0, le=23, description="시")
    minute: int = Field(ge=0, le=59, description="분")


class MarkDoNotContact(_Args):
    reason: Words = Field(description="연락하지 말라고 한 까닭")


class HandoffToHuman(_Args):
    reason: Literal["asked_for_person", "out_of_scope", "schedule_change", "emergency", "other"] = Field(
        description="사람을 찾음 · 답할 수 없는 물음 · 일정 변경 요구 · 안전사고와 긴급 · 그 밖")
    note: MaybeWords = Field("", description="담당자에게 전할 내용")


class EndCall(_Args):
    reason: Literal["done", "wrong_person", "voicemail", "wrong_number", "busy_callback", "do_not_contact", "silence",
                    "time_limit", "handoff", "other"] = Field(description="통화를 마치는 까닭")
    language: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^([a-z]{2,3}(-[A-Za-z]{2,4})?)?$")] = Field(
        "", description="상대가 쓴 언어의 코드. 한국어였으면 비워 둔다.")


class ConfirmPerson(_Args):
    is_person: bool = Field(description="받은 사람이 찾던 그 사람이 맞는가")


ARGS: Mapping[str, type[_Args]] = MappingProxyType({
    "find_contact": FindContact, "propose_contact": ProposeContact, "schedule_fact": ScheduleFact,
    "my_requests": MyRequests, "record_answer": RecordAnswer, "take_message": TakeMessage,
    "report_from_contact": ReportFromContact, "schedule_callback": ScheduleCallback,
    "mark_do_not_contact": MarkDoNotContact, "handoff_to_human": HandoffToHuman, "end_call": EndCall,
    "confirm_person": ConfirmPerson,
})
_DESCRIPTIONS: Mapping[str, str] = MappingProxyType({
    "find_contact": "이 현장 주소록에서 이름이나 담당으로 사람을 찾는다. 전화번호는 주지 않는다.",
    "propose_contact": "상대가 알려 준 새 연락처를 제안으로 남긴다. 담당자가 확인한 뒤에 주소록에 들어간다.",
    "schedule_fact": "작업의 이름·시작일·종료일·상태를 찾는다. 날짜는 이 도구가 준 것만 말한다. "
                     "「말씀드릴 수 없는 내용입니다」가 오면 그대로 전하고 더 캐묻지 않는다.",
    "my_requests": "이 상대에게 최근에 우리가 보낸 요청과 건 통화의 목적을 본다.",
    "record_answer": "우리가 물은 것에 상대가 한 답을 근거 말과 함께 적는다.",
    "take_message": "담당자에게 전할 말을 남긴다. 상대가 자기가 누구라고 밝혔으면 그 이름도 넣고, 돌아온 말을 그대로 전한다.",
    "report_from_contact": "상대가 알린 지연·문제·일정 변경 요청을 보고로 남긴다. 일정은 바뀌지 않고 담당자가 확인한다.",
    "schedule_callback": "상대가 나중에 다시 연락해 달라고 한 때를 남긴다. 날짜는 며칠 뒤인지와 시·분으로만 준다.",
    "mark_do_not_contact": "상대가 연락하지 말라고 했을 때 수신 거부로 표시한다.",
    "handoff_to_human": "사람 담당자에게 넘긴다. 안전사고와 긴급한 일은 곧바로 이 도구로 알린다.",
    "end_call": "통화를 마친다. 음성사서함이면 아무 말도 남기지 않고 이 도구를 부른다.",
    "confirm_person": "받은 사람이 찾던 그 사람인지 확인한 결과를 적는다.",
})


def _schema(model: type[_Args]) -> dict[str, Any]:
    """그 인자 꼴의 JSON Schema(제목 칸은 뺀다 — 모델에게 줄 것만)."""
    def bare(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: bare(item) for key, item in node.items() if key != "title"}
        return [bare(item) for item in node] if isinstance(node, list) else node

    return bare(model.model_json_schema())


_DEFS: Mapping[str, ToolDef] = MappingProxyType({
    name: ToolDef(name, _DESCRIPTIONS[name], _schema(ARGS[name])) for name in ALL
})


def tool_defs(names: Iterable[str]) -> tuple[ToolDef, ...]:
    """그 이름들의 도구 정의(이름표 차례). 묶음에 없는 이름이 있으면 ValueError."""
    wanted = frozenset(names)
    if not wanted <= frozenset(ALL):
        raise ValueError("도구 묶음에 없는 이름입니다")
    return tuple(_DEFS[name] for name in ALL if name in wanted)
