"""연락 하네스의 낱말(Task 64 — 여기서만 정의한다). 나가는 문·들어오는 문·도구 묶음·사건 기록·통로·글과 음성 세션이
모두 이것을 쓰고, 서로를 import 하지 않아도 같은 말을 한다. 표준 라이브러리만 쓴다(DB·제공사·LLM 없음).

- 전화번호는 어느 낱말에도 칸이 없다 — 번호는 줄(연락처·peer_number)에만 있고 코드가 붙인다.
- 값은 만들 때 검사한다(이름표 밖의 등급·코드·종류, 정수가 아닌 id 는 ValueError). 오류 글에 받은 값을 싣지 않는다.
- 사건 이름(events.record 의 rule)은 GATE_RULES 의 값 · EVENT_RULES · `tool:<SHARED_TOOLS·VOICE_ONLY_TOOLS>` · `tool:unknown`
  만 쓴다. 새 사건 이름이 필요하면 EVENT_RULES 에 더한다(소문자·밑줄만 — 번호나 모델 글이 이름에 들어갈 수 없게).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal, Protocol, get_args

Medium = Literal["sms", "call"]  # 하네스가 보는 매체(카카오톡은 보내기만 하는 통로라 매체가 아니다)
CallerClass = Literal[
    "internal", "contact", "contact_multi", "shared", "do_not_contact", "unknown", "withheld", "blocked", "outside_test",
    "outbound",  # 우리가 먼저 건 통화의 상대
]
FactLevel = Literal["all", "trade", "none"]  # 일정 사실을 어디까지: 전부 · 그 협력사·공종 · 없음
OutcomeCode = Literal[  # 이름표의 판정 코드
    "accepted", "queued", "scheduled", "blocked_test", "blocked_hours", "blocked_number", "do_not_contact", "limit_daily",
    "limit_person", "needs_approval", "duplicate", "held_for_review", "not_ready", "not_sendable",
    "unsure",  # 이름표 밖(제공사 리뷰 11-23): 보내기 요청은 나갔는데 결과를 모름 — 「보냈는지 확인 필요」, 줄은 unconfirmed
]
DeliveryState = Literal["sent", "failed", "unsure"]
SHARED_TOOLS = ("find_contact", "propose_contact", "schedule_fact", "my_requests", "record_answer", "take_message",
                "report_from_contact", "schedule_callback", "mark_do_not_contact", "handoff_to_human")  # 음성·글 공통
VOICE_ONLY_TOOLS = ("end_call", "confirm_person")  # 통화에만(전환은 handoff_to_human 안에서)
# 나가는 문의 차례(Outcome.rule)와 그 사건 이름. 1~6 은 설계 규칙 1 의 차례, 7 은 채널 고르기, 0 은 앞 확인.
GATE_RULES: dict[int, str] = {
    0: "ready", 1: "test_mode", 2: "blocked_or_dnc", 3: "working_hours", 4: "limits", 5: "permission", 6: "duplicate",
    7: "channel_choice",
}
# 문 차례 밖의 사건 이름(계획의 Task 65·66·67·68·71·84·88·95 글에서 모음).
EVENT_RULES: frozenset[str] = frozenset({
    "reply_within_grace", "kakao_not_ready", "delivery", "no_answer_retry",  # 나가는 문(65)
    "admit",  # 들어오는 문의 받기 판정(66 — 84·95 가 남김)
    "scope_denied",  # 도구 묶음(67)
    "unsupported_date", "out_of_scope_said", "money_said", "disclosed_to_unknown",  # 뒤 확인(68)
    "reply_failed", "held_for_review",  # 들어온 문자 응대(84)
    "recheck_before_dial", "silence", "time_limit",  # 통화(88)
    "server_restart",  # 다시 뜰 때 닫은 줄(71·88)
})


class NotReady(Exception):
    """쓸 것이 아직 없다(등록되지 않은 통로 등). 아무것도 보내지 않았다. 판정 코드 not_ready 에 맞는다."""


def _check(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _ints(values: Iterable[object], what: str) -> tuple[int, ...]:
    out = tuple(values)
    _check(all(type(v) is int for v in out), f"{what} 는 정수 id 만 받습니다")
    return out  # type: ignore[return-value]


def _unique(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class Actor:
    """보내기·걸기를 부른 쪽. system 은 일꾼(예약된 줄을 보낼 때)."""

    kind: Literal["user", "agent", "system"]
    user_id: int | None
    name: str
    role: str | None


@dataclass(frozen=True)
class Outcome:
    """문의 판정. code 는 이름표의 판정 코드, message 는 한국어, rule 은 걸린 차례(GATE_RULES 의 열쇠, 지나갔으면 None)."""

    code: OutcomeCode
    message: str
    rule: int | None = None
    scheduled_at: datetime | None = None

    def __post_init__(self) -> None:
        _check(self.code in get_args(OutcomeCode), "Outcome.code 는 이름표의 판정 코드만 받습니다")
        _check(self.rule is None or self.rule in GATE_RULES, "Outcome.rule 은 GATE_RULES 의 차례만 받습니다")


@dataclass(frozen=True)
class Candidate:
    """번호로 찾은 연락처 하나와 그 짝(일정·협력사). 공종은 협력사 줄에서 코드가 읽는다(여기 두 번 적지 않는다)."""

    schedule_id: int
    contact_id: int
    company_id: int

    def __post_init__(self) -> None:
        _ints((self.schedule_id, self.contact_id, self.company_id), "Candidate")


def _candidates(values: Iterable[object]) -> tuple[Candidate, ...]:
    out = tuple(values)
    _check(all(isinstance(c, Candidate) for c in out), "candidates 는 Candidate 만 받습니다")
    return out  # type: ignore[return-value]


@dataclass(frozen=True)
class Caller:
    """번호로 코드가 정한 상대. 등급은 말·글로 한 주장으로 바뀌지 않는다."""

    caller_class: CallerClass
    candidates: tuple[Candidate, ...]
    user_id: int | None  # internal 일 때 그 계정

    def __post_init__(self) -> None:
        _check(self.caller_class in get_args(CallerClass), "Caller.caller_class 가 등급표에 없습니다")
        object.__setattr__(self, "candidates", _candidates(self.candidates))
        _check(self.user_id is None or type(self.user_id) is int, "Caller.user_id 는 정수 id 나 None 입니다")


@dataclass(frozen=True)
class Scope:
    """그 상대에게 도구가 보일 수 있는 범위. 도구는 불릴 때마다 이것만 보고, 모델이 준 인자로 넓히지 않는다.

    schedule_ids — 볼 수 있는 일정(internal 은 그 계정이 볼 수 있는 일정 전부, 연락처 등급은 후보 일정).
    candidates — 일정마다 그 상대의 짝(일정·연락처·협력사). 연락처·협력사 범위는 이 짝에서만 나온다(contact_ids·company_ids).
    personal — 「본인에게 온 요청」을 말해도 되는가. granted — 현장이 정해졌을 때 줄 사실 수준.
    site_required — 후보 현장이 여럿이라 고르기 전(contact_multi). 그동안 facts 는 "none" 이고, pinned(일정) 이 한 현장으로 좁힌다.
    """

    caller_class: CallerClass
    schedule_ids: tuple[int, ...]
    candidates: tuple[Candidate, ...]
    personal: bool
    granted: FactLevel
    site_required: bool = False

    def __post_init__(self) -> None:
        _check(self.caller_class in get_args(CallerClass), "Scope.caller_class 가 등급표에 없습니다")
        _check(self.granted in get_args(FactLevel), "Scope.granted 는 all·trade·none 가운데 하나입니다")
        schedule_ids = _ints(self.schedule_ids, "Scope.schedule_ids")
        candidates = _candidates(self.candidates)
        _check(all(c.schedule_id in schedule_ids for c in candidates), "Scope 의 짝 일정이 schedule_ids 에 없습니다")
        _check(type(self.personal) is bool and type(self.site_required) is bool, "Scope 의 참거짓 칸은 bool 만 받습니다")
        object.__setattr__(self, "schedule_ids", schedule_ids)
        object.__setattr__(self, "candidates", candidates)

    @property
    def facts(self) -> FactLevel:
        """지금 말할 수 있는 사실 수준 — 현장을 고르기 전에는 늘 "none"."""
        return "none" if self.site_required else self.granted

    @property
    def contact_ids(self) -> tuple[int, ...]:
        return _unique(c.contact_id for c in self.candidates)

    @property
    def company_ids(self) -> tuple[int, ...]:
        return _unique(c.company_id for c in self.candidates)

    def pinned(self, schedule_id: int) -> "Scope":
        """그 현장 하나로 좁힌 범위(그 일정의 짝만). 이 범위의 일정이 아니면 ValueError — 고른 뒤에 넓히지 못한다."""
        _check(type(schedule_id) is int and schedule_id in self.schedule_ids, "그 현장은 이 범위의 후보가 아닙니다")
        pairs = tuple(c for c in self.candidates if c.schedule_id == schedule_id)
        return Scope(self.caller_class, (schedule_id,), pairs, self.personal, self.granted)


@dataclass(frozen=True)
class Ref:
    """사건·답·보고가 붙는 줄(outreach_messages 또는 outreach_calls 의 id)."""

    kind: Literal["message", "call"]
    row_id: int

    def __post_init__(self) -> None:
        _check(self.kind in ("message", "call"), "Ref.kind 는 message·call 가운데 하나입니다")
        _ints((self.row_id,), "Ref.row_id")


@dataclass(frozen=True)
class Delivered:
    """통로가 돌려준 결과 — 셋 가운데 하나. fail_text 는 한국어이고 번호·키가 없다.

    sent — 제공사가 받았다(provider_id). failed — 가지 않았음이 확실하다(고쳐서 다시 보내도 된다).
    unsure — 보내기 요청은 나갔는데 결과를 모른다(시간 초과·5xx·409, 제공사의 maybe_sent). 실패로 적으면 다시 보내져 글이
    두 번 가므로 「보냈는지 확인 필요」(Outcome "unsure", 줄 unconfirmed)로 두고 사람이 정한다.
    """

    state: DeliveryState
    provider_id: str | None = None
    fail_code: str | None = None
    fail_text: str | None = None

    def __post_init__(self) -> None:
        _check(self.state in get_args(DeliveryState), "Delivered.state 는 sent·failed·unsure 가운데 하나입니다")

    @property
    def ok(self) -> bool:
        """보냈음이 확실한가(sent). failed·unsure 는 거짓 — 둘은 state 로 가른다."""
        return self.state == "sent"


def _frozen(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _frozen(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_frozen(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class ToolDef:
    """도구 하나의 정의. 음성 세션과 글 세션이 같은 객체를 받으므로 parameters 는 읽기 전용이다(만들 때 깊이 복사해 얼림 —
    dict 는 MappingProxyType, 목록은 tuple). 세션·SDK 에 넘길 JSON Schema 는 json_schema() 가 새 dict 로 준다."""

    name: str
    description: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _frozen(self.parameters))

    def json_schema(self) -> dict[str, Any]:
        return _plain(self.parameters)


class Channel(Protocol):
    """통로: 문자·카카오톡·통화가 하나씩 구현하고 registry 에 스스로 등록한다. 판정은 하지 않는다(문이 이미 했다).
    deliver 를 부르는 곳은 나가는 문 하나뿐이다."""

    name: str

    async def deliver(self, row_id: int) -> Delivered: ...
